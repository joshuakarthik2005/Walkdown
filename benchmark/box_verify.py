"""Text + boxes + verifier: verify the merged text-and-box candidates and score all variants.

Per image, the cached SAM "rust" masks and the cached box-prompt masks are
merged exactly as in ``box_prompt`` (text + boxes). Each merged candidate that
is essentially an existing text-only candidate (mask IoU >= 0.9) reuses that
candidate's cached verdict; every other merged candidate is new and is sent to
the same verifier (hosted Muse Spark, low effort, cached on
WALKDOWN_DATA_DIR/runs/verify/meta/low/ under ids ``<stem>#tb<k>``).
Invalid replies fail open (kept), as everywhere else.

Variants scored with sam_eval levels: text only, text only + verifier,
text + boxes, text + boxes + verifier. Resumable through a journal; stops at
``--max-usd`` of new spend. ``--count-only`` makes no API calls and reports how
many new candidates there are (for the cost estimate).

    .venv\\Scripts\\python.exe -m benchmark.box_verify test --count-only
    .venv\\Scripts\\python.exe -m benchmark.box_verify test --max-usd 14
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from backend.clients.cost import CostLedger
from backend.perception.sam import parse_output
from backend.perception.tiling import merge_instances
from benchmark.box_prompt import CACHE as BOX_CACHE
from benchmark.download_dataset import DATA_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR, ground_truth
from benchmark.sam_eval import aggregate, image_stats
from benchmark.splits import load_split
from benchmark.verify_eval import _cached_verify, label

RESULTS_DIR = Path(__file__).parent / "results"
REUSE_IOU = 0.9
CALLS_PER_PROCESS = 2
VARIANTS = ("text_only", "text_only_verified", "text_plus_boxes", "text_plus_boxes_verified")


def journal_path(split: str) -> Path:
    return DATA_DIR / "runs" / f"box_verify_{split}_journal.jsonl"


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = int((a & b).sum())
    return inter / max(1, int((a | b).sum()))


def candidates(rel: str) -> tuple[list, list, list[dict]]:
    """Text instances, merged text+boxes instances, and one record per merged instance (id, reuse or new)."""
    stem = Path(rel).stem
    text = parse_output((SAM_DIR / "rust" / (stem + ".txt")).read_text(encoding="utf-8"), 640, 640)
    box_path = BOX_CACHE / "sam" / (stem + ".txt")
    boxes = parse_output(box_path.read_text(encoding="utf-8"), 640, 640) if box_path.exists() else []
    merged = merge_instances(text + boxes)
    records = []
    for inst in merged:
        best = max(text, key=lambda t: _iou(t.mask, inst.mask), default=None)
        if best is not None and _iou(best.mask, inst.mask) >= REUSE_IOU:
            records.append(dict(id=f"{stem}#{best.object_id}", new=False))
        else:
            records.append(dict(id=f"{stem}#tb{inst.object_id}", new=True))
    return text, merged, records


def count_image(rel: str) -> tuple[int, int]:
    _, merged, records = candidates(rel)
    return len(merged), sum(r["new"] for r in records)


def process_image(rel: str, effort: str) -> tuple[str, dict | None, float, str | None]:
    """Verify new merged candidates on one image and return per-variant stats (runs in a worker process)."""
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    text, merged, records = candidates(rel)
    truth = ground_truth([rel])[rel]
    union = np.logical_or.reduce(truth) if truth else np.zeros((640, 640), bool)
    text_cands = [dict(id=f"{Path(rel).stem}#{t.object_id}", image=rel, instance=t) for t in text]
    merged_cands = [dict(id=r["id"], image=rel, instance=m) for r, m in zip(records, merged)]

    def safe(c: dict):
        try:  # exceptions must not escape a worker process (see verify_scale)
            return _cached_verify(c, "meta", effort, ledger)
        except Exception as err:  # noqa: BLE001
            return f"{type(err).__name__}: {str(err)[:200]}"

    with ThreadPoolExecutor(max_workers=CALLS_PER_PROCESS) as pool:
        text_v = list(pool.map(safe, text_cands))
        merged_v = list(pool.map(safe, merged_cands))
    errors = [v for v in text_v + merged_v if isinstance(v, str)]
    if errors:
        return rel, None, ledger.total(), errors[0]
    keep = lambda v: v.grade.is_defect if v.grade else True  # noqa: E731 - fail open
    text_kept = [t for t, v in zip(text, text_v) if keep(v)]
    merged_kept = [m for m, v in zip(merged, merged_v) if keep(v)]
    rows = []
    for r, m, v in zip(records, merged, merged_v):
        lab, cov = label(m.mask, union)
        rows.append(dict(id=r["id"], new=r["new"], label=lab, accepted=keep(v), valid=v.grade is not None,
                         usd=(v.usd or 0.0) if r["new"] else 0.0, latency=v.latency_s if r["new"] else None))
    stats = {"text_only": image_stats(truth, merge_instances(text)),
             "text_only_verified": image_stats(truth, merge_instances(text_kept)),
             "text_plus_boxes": image_stats(truth, merged),
             "text_plus_boxes_verified": image_stats(truth, merged_kept)}
    return rel, dict(image=rel, rows=rows, stats=stats), ledger.total(), None


def _restore(stats: dict) -> dict:
    """JSON turns the float IoU-threshold keys into strings; put them back for ``aggregate``."""
    return {**stats, "inst": {float(k): v for k, v in stats["inst"].items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--count-only", action="store_true")
    args = ap.parse_args()
    images = load_split(args.split)

    if args.count_only:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            counts = list(pool.map(count_image, images, chunksize=8))
        total, new = sum(c[0] for c in counts), sum(c[1] for c in counts)
        print(f"{args.split}: {total} merged candidates, {new} new (need verification), {total - new} reuse "
              f"a text-only verdict")
        return 0

    journal = journal_path(args.split)
    done = {}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["image"]] = r
    todo = [rel for rel in images if rel not in done]
    print(f"{len(done)} images already done, {len(todo)} to go", flush=True)
    t0, spent, finished = time.perf_counter(), 0.0, 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        pending, queue, stopping = {}, iter(todo), False

        def submit_next() -> None:
            rel = next(queue, None)
            if rel is not None:
                pending[pool.submit(process_image, rel, args.effort)] = rel

        for _ in range(args.workers):
            submit_next()
        while pending:
            fut = next(as_completed(pending))
            pending.pop(fut)
            rel, record, usd, error = fut.result()
            spent += usd
            if record is None:
                print(f"{rel}: {error}; rerun to retry", flush=True)
            else:
                with journal.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
                done[rel] = record
                finished += 1
                if finished % 50 == 0:
                    print(f"{finished}/{len(todo)} images, new spend ${spent:.2f}", flush=True)
            if spent > args.max_usd and not stopping:
                stopping = True
                print(f"budget reached: ${spent:.2f}", flush=True)
            if not stopping:
                submit_next()

    recs = [done[rel] for rel in images if rel in done]
    rows = [r for rec in recs for r in rec["rows"]]
    new = [r for r in rows if r["new"]]
    tps = [r for r in rows if r["label"] == "TP"]
    new_tps = [r for r in new if r["label"] == "TP"]
    lat = [r["latency"] for r in new if r["latency"]]
    out = dict(split=args.split, effort=args.effort, images=len(images), images_done=len(recs),
               complete=len(recs) == len(images), merged_candidates=len(rows), new_candidates=len(new),
               new_label_counts={k: sum(r["label"] == k for r in new) for k in ("TP", "FP", "ambiguous")},
               new_accepted_share=sum(r["accepted"] for r in new) / len(new) if new else None,
               new_invalid_reply_rate=sum(not r["valid"] for r in new) / len(new) if new else None,
               tp_retention_all_merged=sum(r["accepted"] for r in tps) / len(tps) if tps else None,
               tp_retention_new=sum(r["accepted"] for r in new_tps) / len(new_tps) if new_tps else None,
               new_verify_usd=sum(r["usd"] for r in new), latency_s_median_new=float(np.median(lat)) if lat else None,
               last_chunk=dict(wall_s=time.perf_counter() - t0, images=finished, usd=spent),
               variants={k: aggregate([_restore(rec["stats"][k]) for rec in recs]) for k in VARIANTS})
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"box_verify_{args.split}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "variants"}, indent=1))
    for k, s in out["variants"].items():
        i5, i3 = s["instance"]["iou>=0.5"], s["instance"]["iou>=0.3"]
        print(f"{k:26} img-det {s['image']['detection_rate_on_positives']:.3f} | pixel P {s['pixel']['precision']:.3f} "
              f"R {s['pixel']['recall']:.3f} IoU {s['pixel']['iou']:.3f} | inst@0.5 P {i5['precision']:.3f} "
              f"R {i5['recall']:.3f} F1 {i5['f1']:.3f} | inst@0.3 F1 {i3['f1']:.3f} | cands/img "
              f"{s['predictions_per_image']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
