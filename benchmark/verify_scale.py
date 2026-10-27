"""Verify every SAM candidate on a split with hosted Muse Spark, low memory and resumable in chunks.

Streams one image at a time (masks are never all held in memory), runs at most
``--workers`` images in parallel worker processes, caches every verdict on WALKDOWN_DATA_DIR
(shared with verify_eval), and appends one journal line per finished image so
later chunks skip finished images without re-decoding their masks. Stops at
``--max-usd`` of new spend or after ``--max-minutes``, finishing the images in
flight. Statistics are always computed from the whole journal.

Reports TP retention (share of coverage-labelled TPs the verifier keeps),
severity distribution, invalid-reply rate, consistency flags, cost and
throughput. FP rejection against dataset labels is reported but marked NOT
reliable (dataset label gaps; see DECISIONS.md).

    .venv\\Scripts\\python.exe -m benchmark.verify_scale test --workers 8 --max-usd 34 --max-minutes 9
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from backend.clients.cost import CostLedger
from backend.perception.sam import parse_output
from benchmark.download_dataset import DATA_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR, ground_truth
from benchmark.splits import load_split
from benchmark.verify_eval import _cached_verify, label

RESULTS_DIR = Path(__file__).parent / "results"
CALLS_PER_PROCESS = 2  # with 4 processes: 8 concurrent calls; more concurrency only raised server latency


def journal_path(split: str, effort: str) -> Path:
    return DATA_DIR / "runs" / f"verify_scale_{split}_{effort}_journal.jsonl"


def read_journal(path: Path) -> dict[str, list[dict]]:
    """Rows per finished image."""
    done: dict[str, list[dict]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["image"]] = r["rows"]
    return done


def summarise(split: str, effort: str, images: list[str], done: dict[str, list[dict]], extra: dict) -> dict:
    """Statistics over every journaled image."""
    rows = [r for rel in images if rel in done for r in done[rel]]
    tps = [r for r in rows if r["label"] == "TP"]
    fps = [r for r in rows if r["label"] == "FP"]
    valid = [r for r in rows if r["valid"]]
    paid = [r for r in rows if r["usd"] > 0]
    return dict(
        split=split, provider="meta", effort=effort, images=len(images),
        images_done=sum(rel in done for rel in images), candidates=len(rows),
        complete=all(rel in done for rel in images),
        label_counts={k: sum(r["label"] == k for r in rows) for k in ("TP", "FP", "ambiguous")},
        tp_retention=sum(r["accepted"] for r in tps) / len(tps) if tps else None,
        accepted_share=sum(r["accepted"] for r in rows) / len(rows) if rows else None,
        fp_rejection_vs_dataset_labels_NOT_RELIABLE=(sum(not r["accepted"] for r in fps) / len(fps)) if fps else None,
        invalid_reply_rate=1 - len(valid) / len(rows) if rows else None,
        severity_histogram={s: sum(r["severity"] == s for r in rows) for s in range(1, 6)},
        flags={f: sum(f in r["flags"] for r in rows) for f in sorted({f for r in rows for f in r["flags"]})},
        cost=dict(usd_all_candidates=sum(r["usd"] for r in rows),
                  usd_per_candidate_mean=statistics.mean(r["usd"] for r in paid) if paid else None,
                  reasoning_tokens_mean=statistics.mean(r["reasoning"] for r in paid) if paid else None),
        latency_s_median=statistics.median(r["latency"] for r in paid) if paid else None,
        **extra,
    )


def process_image(rel: str, effort: str) -> tuple[str, list[dict] | None, float, int, str | None]:
    """Verify every candidate on one image (runs in a worker process)."""
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    sam_path = SAM_DIR / "rust" / (Path(rel).stem + ".txt")
    gt = ground_truth([rel])[rel]
    union = np.logical_or.reduce(gt) if gt else np.zeros((640, 640), bool)
    cands = []
    for inst in parse_output(sam_path.read_text(encoding="utf-8"), 640, 640):
        lab, cov = label(inst.mask, union)
        cands.append(dict(id=f"{Path(rel).stem}#{inst.object_id}", image=rel, instance=inst, label=lab,
                          coverage=cov))
    # The API calls are I/O-bound, so a few threads per process overlap them.
    def safe(c: dict):
        # Exceptions must not escape a worker process: some (e.g. openai.APIConnectionError) cannot be
        # pickled back to the parent and would break the whole pool. Failed candidates are retried later.
        try:
            return _cached_verify(c, "meta", effort, ledger)
        except Exception as err:  # noqa: BLE001
            return f"{type(err).__name__}: {str(err)[:200]}"

    with ThreadPoolExecutor(max_workers=CALLS_PER_PROCESS) as pool:
        verdicts = list(pool.map(safe, cands))
    errors = [v for v in verdicts if isinstance(v, str)]
    if errors:  # not journaled: the image is retried in a later chunk (finished verdicts are cached)
        return rel, None, ledger.total(), ledger.summary()["calls"], errors[0]
    rows = []
    for cand, v in zip(cands, verdicts):
        g = v.grade
        rows.append(dict(id=cand["id"], label=cand["label"], coverage=round(cand["coverage"], 3),
                         accepted=g.is_defect if g else True, valid=g is not None,
                         severity=g.severity if g and g.is_defect else None, flags=v.flags,
                         usd=v.usd or 0.0, latency=v.latency_s, reasoning=v.reasoning_tokens))
    return rel, rows, ledger.total(), ledger.summary()["calls"], None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-usd", type=float, required=True, help="cap on new spend in this chunk")
    ap.add_argument("--max-minutes", type=float, default=None)
    args = ap.parse_args()
    workers = min(args.workers, 20)

    images = load_split(args.split)
    journal = journal_path(args.split, args.effort)
    done = read_journal(journal)
    todo = [rel for rel in images if rel not in done]
    print(f"{len(done)} images already done, {len(todo)} to go", flush=True)

    t0 = time.perf_counter()
    spent = calls = finished = 0
    # Processes, not threads: mask decoding is pure Python and holds the GIL.
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {}
        queue = iter(todo)
        stopping = False

        def submit_next() -> None:
            rel = next(queue, None)
            if rel is not None:
                pending[pool.submit(process_image, rel, args.effort)] = rel

        for _ in range(workers):
            submit_next()
        while pending:
            fut = next(as_completed(pending))
            pending.pop(fut)
            rel, rows, new_usd, new_calls, error = fut.result()
            if rows is None:
                print(f"{rel}: {error}; will retry in a later chunk", flush=True)
            else:
                with journal.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(dict(image=rel, rows=rows)) + "\n")
                finished += 1
            spent, calls = spent + new_usd, calls + new_calls
            if finished % 20 == 0:
                print(f"{finished} images this chunk, new spend ${spent:.2f}", flush=True)
            if spent > args.max_usd:
                stopping = True
                print(f"budget reached: ${spent:.2f}", flush=True)
            if args.max_minutes and time.perf_counter() - t0 > 60 * args.max_minutes:
                stopping = True
            if not stopping:
                submit_next()
    wall = time.perf_counter() - t0

    result = summarise(args.split, args.effort, images, read_journal(journal), dict(
        last_chunk=dict(wall_s=wall, workers=workers, images=finished, new_calls=calls, usd=spent,
                        new_calls_per_min=60 * calls / wall if wall else None)))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"verify_scale_{args.split}_meta_{args.effort}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("images_done", "images", "candidates", "complete", "tp_retention",
                                              "invalid_reply_rate", "cost", "last_chunk")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
