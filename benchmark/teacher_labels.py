"""Teacher labels for the Glimmer verifier distillation, on the clean training pool only.

Every input to training comes from open weights, never from a hosted Meta model (Meta Model API terms
10.1(ix)):
- candidates: SAM 3.1 **open weights** on Modal (``walkdown-sam31``), text prompt "rust", on the 585 images of
  ``benchmark/splits/train_pool.txt`` (near-duplicate clusters disjoint from dev and test; DECISIONS.md);
- labels: **Muse Spark Open** on Baseten, the product's verifier prompt and schema, low effort.

No hosted SAM masks, hosted box proposals or hosted Muse Spark verdicts are used. The dataset coverage label
(TP / FP / ambiguous against the annotations) is stored next to each teacher label for analysis only.

Stages (both resumable):
    sam     segment uncached images on Modal, 50 per call; RLE records cached per image
    verify  teacher verdicts per candidate (verdict cache shared with verify_eval, suffix ``-sam-modal``);
            one journal line per finished image

    .venv\\Scripts\\python.exe -m benchmark.teacher_labels sam --max-images 15
    .venv\\Scripts\\python.exe -m benchmark.teacher_labels verify --max-images 15 --max-usd 1
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from backend.clients.cost import CostLedger
from backend.perception.sam_open import segment_images_open, to_instances
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import ground_truth
from benchmark.splits import load_split
from benchmark.verify_eval import _cached_verify, label

SPLIT = "train_pool"
SAM_DIR = DATA_DIR / "runs" / "sam_open" / "rust"
JOURNAL = DATA_DIR / "runs" / "teacher_train_pool_journal.jsonl"
LEDGER = DATA_DIR / "runs" / "cost_ledger.jsonl"
RESULT = Path(__file__).parent / "results" / "teacher_labels_train_pool.json"
EFFORT = "low"
SUFFIX = "-sam-modal"
MODAL_BATCH = 50
IMAGES_IN_FLIGHT = 4
THREADS = 2  # per image: 4 x 2 = 8 calls in flight, the concurrency measured best for Baseten (RESULTS.md section 6)


def sam_path(rel: str) -> Path:
    return SAM_DIR / (Path(rel).stem + ".json")


def run_sam(images: list[str], ledger: CostLedger) -> None:
    """SAM 3.1 open weights on every uncached image, MODAL_BATCH images per call."""
    SAM_DIR.mkdir(parents=True, exist_ok=True)
    todo = [rel for rel in images if not sam_path(rel).exists()]
    print(f"{len(images) - len(todo)} cached, {len(todo)} to segment", flush=True)
    for i in range(0, len(todo), MODAL_BATCH):
        batch = todo[i:i + MODAL_BATCH]
        t0 = time.perf_counter()
        records = segment_images_open([RAW_DIR / rel for rel in batch], "rust", ledger=ledger,
                                      job="teacher-sam-open")
        for rel, recs in zip(batch, records):
            sam_path(rel).write_text(json.dumps(recs), encoding="utf-8")
        print(f"{i + len(batch)}/{len(todo)} segmented ({time.perf_counter() - t0:.0f} s)", flush=True)


def read_journal() -> dict[str, list[dict]]:
    done: dict[str, list[dict]] = {}
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["image"]] = r["rows"]
    return done


def verify_image(rel: str, ledger: CostLedger) -> list[dict] | str:
    """Teacher verdicts for every open-weights candidate on one image; an error string if any call failed."""
    gt = ground_truth([rel]).get(rel) or []
    union = np.logical_or.reduce(gt) if gt else np.zeros((640, 640), bool)
    cands = []
    for inst in to_instances(json.loads(sam_path(rel).read_text(encoding="utf-8")), frame=0):
        lab, cov = label(inst.mask, union)
        cands.append(dict(id=f"{Path(rel).stem}#{inst.object_id}", image=rel, instance=inst, label=lab,
                          coverage=cov))

    def safe(c: dict):
        try:
            return _cached_verify(c, "baseten", EFFORT, ledger, suffix=SUFFIX)
        except Exception as err:  # noqa: BLE001  retried in a later run (finished verdicts are cached)
            return f"{type(err).__name__}: {str(err)[:200]}"

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        verdicts = list(pool.map(safe, cands))
    errors = [v for v in verdicts if isinstance(v, str)]
    if errors:
        return errors[0]
    rows = []
    for c, v in zip(cands, verdicts):
        g = v.grade
        rows.append(dict(id=c["id"], object_id=c["instance"].object_id, box=list(c["instance"].box),
                         sam_score=round(c["instance"].confidence or 0, 3), label=c["label"],
                         coverage=round(c["coverage"], 3), valid=g is not None,
                         grade=g.model_dump(mode="json") if g else None, flags=v.flags, usd=v.usd or 0.0,
                         latency=v.latency_s))
    return rows


def run_verify(images: list[str], ledger: CostLedger, max_usd: float) -> None:
    import threading
    done = read_journal()
    todo = [rel for rel in images if rel not in done]
    print(f"{len(done)} images journaled, {len(todo)} to verify", flush=True)
    start = ledger.total()
    lock = threading.Lock()
    finished = [0]

    def one(rel: str) -> None:
        if ledger.total() - start > max_usd:
            return
        rows = verify_image(rel, ledger)
        with lock:
            if isinstance(rows, str):
                print(f"{rel}: {rows}; retry later", flush=True)
                return
            with JOURNAL.open("a", encoding="utf-8") as f:
                f.write(json.dumps(dict(image=rel, rows=rows)) + "
")
            finished[0] += 1
            if finished[0] % 20 == 0:
                print(f"{finished[0]}/{len(todo)} images, new spend ${ledger.total() - start:.2f}", flush=True)

    with ThreadPoolExecutor(max_workers=IMAGES_IN_FLIGHT) as pool:
        list(pool.map(one, todo))
    if ledger.total() - start > max_usd:
        print(f"budget reached: ${ledger.total() - start:.2f}", flush=True)


def summarise(images: list[str]) -> dict:
    done = read_journal()
    rows = [r for rel in images if rel in done for r in done[rel]]
    valid = [r for r in rows if r["valid"]]
    paid = [r for r in rows if r["usd"] > 0]
    acc = [r for r in valid if r["grade"]["is_defect"]]
    by_label = {k: [r for r in valid if r["label"] == k] for k in ("TP", "FP", "ambiguous")}
    return dict(
        split=SPLIT, sam="SAM 3.1 open weights (Modal)", teacher="Muse Spark Open (Baseten), low effort",
        images=len(images), images_done=sum(rel in done for rel in images), candidates=len(rows),
        invalid_reply_rate=1 - len(valid) / len(rows) if rows else None,
        accepted=len(acc), rejected=len(valid) - len(acc),
        accept_share_by_dataset_label={k: (sum(r["grade"]["is_defect"] for r in v) / len(v) if v else None,
                                           len(v)) for k, v in by_label.items()},
        severity_histogram={s: sum(r["grade"]["severity"] == s for r in acc) for s in range(1, 6)},
        defect_types={t: sum(r["grade"]["defect_type"] == t for r in acc)
                      for t in sorted({r["grade"]["defect_type"] for r in acc})},
        usd_teacher=round(sum(r["usd"] for r in rows), 4),
        usd_per_candidate=statistics.mean(r["usd"] for r in paid) if paid else None,
        latency_s_median=statistics.median(r["latency"] for r in paid) if paid else None,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("sam", "verify", "summary"))
    ap.add_argument("--max-images", type=int, default=None)
    ap.add_argument("--max-usd", type=float, default=1.0, help="cap on new Baseten spend (verify)")
    args = ap.parse_args()
    images = load_split(SPLIT)[:args.max_images]
    ledger = CostLedger(LEDGER)
    if args.stage == "sam":
        run_sam(images, ledger)
    elif args.stage == "verify":
        run_verify(images, ledger, args.max_usd)
    result = summarise(images)
    if args.stage != "sam":
        RESULT.parent.mkdir(exist_ok=True)
        RESULT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
