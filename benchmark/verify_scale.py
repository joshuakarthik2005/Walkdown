"""Verify every SAM candidate on a split with hosted Muse Spark, low memory and resumable.

Streams one image at a time (masks are never all held in memory), runs at
most ``--workers`` images in parallel (each image's candidates sequentially,
so at most ``--workers`` calls are in flight), caches every verdict on
WALKDOWN_DATA_DIR (shared with verify_eval), and stops at ``--max-usd``.
With ``--wait-for-sam`` it first waits until SAM outputs exist for the whole split.

Reports TP retention (share of coverage-labelled TPs the verifier keeps),
severity distribution, invalid-reply rate, consistency flags, cost and
throughput. FP rejection against dataset labels is computed but marked as
NOT a reliable metric (label gaps, see DECISIONS.md).

    .venv\\Scripts\\python.exe -m benchmark.verify_scale test --workers 10 --max-usd 35 --wait-for-sam
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from backend.clients.cost import CostLedger
from backend.perception.sam import parse_output
from benchmark.download_dataset import DATA_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR, ground_truth
from benchmark.splits import load_split
from benchmark.verify_eval import _cached_verify, label

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--wait-for-sam", action="store_true")
    args = ap.parse_args()
    workers = min(args.workers, 20)

    images = load_split(args.split)
    sam_path = lambda rel: SAM_DIR / "rust" / (Path(rel).stem + ".txt")  # noqa: E731
    while args.wait_for_sam and not all(sam_path(r).exists() for r in images):
        missing = sum(not sam_path(r).exists() for r in images)
        print(f"waiting for SAM: {missing} images left", flush=True)
        time.sleep(60)

    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    stop = threading.Event()
    lock = threading.Lock()
    rows: list[dict] = []
    t0 = time.perf_counter()

    def one_image(rel: str) -> None:
        if stop.is_set() or not sam_path(rel).exists():
            return
        gt = ground_truth([rel])[rel]
        union = np.logical_or.reduce(gt) if gt else np.zeros((640, 640), bool)
        for inst in parse_output(sam_path(rel).read_text(encoding="utf-8"), 640, 640):
            if stop.is_set():
                return
            lab, cov = label(inst.mask, union)
            cand = dict(id=f"{Path(rel).stem}#{inst.object_id}", image=rel, instance=inst, label=lab, coverage=cov)
            v = _cached_verify(cand, "meta", args.effort, ledger)
            g = v.grade
            with lock:
                rows.append(dict(label=lab, accepted=g.is_defect if g else True, valid=g is not None,
                                 severity=g.severity if g and g.is_defect else None, flags=v.flags,
                                 usd=v.usd or 0.0, latency=v.latency_s, reasoning=v.reasoning_tokens))
                n = len(rows)
            if ledger.total() > args.max_usd:
                stop.set()
                print(f"budget reached: ${ledger.total():.2f}", flush=True)
            if n % 250 == 0:
                print(f"{n} candidates, new spend ${ledger.total():.2f}, "
                      f"{n / (time.perf_counter() - t0):.1f}/s", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one_image, images))
    wall = time.perf_counter() - t0

    tps = [r for r in rows if r["label"] == "TP"]
    fps = [r for r in rows if r["label"] == "FP"]
    valid = [r for r in rows if r["valid"]]
    result = dict(
        split=args.split, provider="meta", effort=args.effort, images=len(images), candidates=len(rows),
        complete=not stop.is_set(),
        label_counts={k: sum(r["label"] == k for r in rows) for k in ("TP", "FP", "ambiguous")},
        tp_retention=sum(r["accepted"] for r in tps) / len(tps) if tps else None,
        accepted_share=sum(r["accepted"] for r in rows) / len(rows) if rows else None,
        fp_rejection_vs_dataset_labels_NOT_RELIABLE=(sum(not r["accepted"] for r in fps) / len(fps)) if fps else None,
        invalid_reply_rate=1 - len(valid) / len(rows) if rows else None,
        severity_histogram={s: sum(r["severity"] == s for r in rows) for s in range(1, 6)},
        flags={f: sum(f in r["flags"] for r in rows) for f in sorted({f for r in rows for f in r["flags"]})},
        cost=dict(usd_new_this_run=ledger.total(), usd_per_candidate_mean=statistics.mean(r["usd"] for r in rows)
                  if rows else None, usd_all_candidates=sum(r["usd"] for r in rows),
                  reasoning_tokens_mean=statistics.mean(r["reasoning"] for r in rows) if rows else None),
        throughput=dict(wall_s=wall, workers=workers, new_calls=ledger.summary()["calls"],
                        new_calls_per_min=60 * ledger.summary()["calls"] / wall if wall else None,
                        latency_s_median=statistics.median(r["latency"] for r in rows) if rows else None),
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"verify_scale_{args.split}_meta_{args.effort}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
