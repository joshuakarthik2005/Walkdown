"""Evaluate SAM 3.1 alone on a split with a frozen prompt (chosen on dev).

Three levels of metrics, because the dataset's annotation granularity (many
small patches per image) differs from SAM's (fewer, larger regions):

1. Instance: greedy one-to-one matching, precision/recall/F1 at IoU 0.5 and 0.3.
2. Pixel: union of predicted masks vs union of ground-truth masks per image;
   micro precision/recall/IoU over all pixels, plus mean per-image IoU.
3. Image: "any corrosion found" vs "any corrosion annotated". With no
   negatives yet this is detection rate on positives only.

Raw SAM outputs are cached on WALKDOWN_DATA_DIR (shared with the dry run),
so re-scoring is free.

    .venv\\Scripts\\python.exe -m benchmark.sam_eval test rust --max-usd 3.70
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from backend.clients.cost import CostLedger, sam_image_cost
from backend.perception.sam import parse_output
from benchmark.download_dataset import DATA_DIR
from benchmark.sam_dryrun import RUN_DIR, _slug, ground_truth, run_prompt
from benchmark.seg_metrics import ImageResult, Prediction, evaluate
from benchmark.splits import load_split

RESULTS_DIR = Path(__file__).parent / "results"


def score_levels(outputs: dict[str, str], gt: dict[str, list[np.ndarray]], size: int = 640) -> dict:
    """Instance (IoU 0.5 and 0.3), pixel and image-level metrics."""
    parsed = {rel: parse_output(text, size, size) for rel, text in outputs.items()}
    instance = {}
    for thr in (0.5, 0.3):
        m = evaluate([ImageResult(rel, gt[rel], [Prediction(i.mask, i.confidence or 0.0) for i in parsed[rel]])
                      for rel in outputs], iou_threshold=thr)
        instance[f"iou>={thr}"] = dict(precision=m.precision, recall=m.recall, f1=m.f1, tp=m.tp, fp=m.fp, fn=m.fn,
                                       mean_matched_iou=m.mean_matched_iou)
    tp_px = fp_px = fn_px = 0
    per_image_iou = []
    found = annotated = found_and_annotated = 0
    for rel in outputs:
        pred = np.zeros((size, size), bool)
        for inst in parsed[rel]:
            pred |= inst.mask
        truth = np.logical_or.reduce(gt[rel]) if gt[rel] else np.zeros((size, size), bool)
        tp, fp, fn = int((pred & truth).sum()), int((pred & ~truth).sum()), int((~pred & truth).sum())
        tp_px, fp_px, fn_px = tp_px + tp, fp_px + fp, fn_px + fn
        per_image_iou.append(tp / (tp + fp + fn) if tp + fp + fn else 1.0)
        has_pred, has_gt = bool(parsed[rel]), bool(gt[rel])
        found += has_pred
        annotated += has_gt
        found_and_annotated += has_pred and has_gt
    pixel = dict(precision=tp_px / (tp_px + fp_px) if tp_px + fp_px else 0.0,
                 recall=tp_px / (tp_px + fn_px) if tp_px + fn_px else 0.0,
                 iou=tp_px / (tp_px + fp_px + fn_px) if tp_px + fp_px + fn_px else 0.0,
                 mean_image_iou=float(np.mean(per_image_iou)))
    n = len(outputs)
    image = dict(images=n, annotated=annotated, negatives=n - annotated, with_any_prediction=found,
                 detection_rate_on_positives=found_and_annotated / annotated if annotated else 0.0,
                 false_alarm_rate_on_negatives=((found - found_and_annotated) / (n - annotated))
                 if n - annotated else None)
    counts = [len(v) for v in parsed.values()]
    return dict(instance=instance, pixel=pixel, image=image,
                predictions_per_image=float(np.mean(counts)),
                gt_instances_per_image=float(np.mean([len(gt[r]) for r in outputs])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("prompt")
    ap.add_argument("--max-usd", type=float, required=True)
    args = ap.parse_args()

    images = load_split(args.split)
    cache = RUN_DIR / _slug(args.prompt)
    uncached = sum(not (cache / (Path(r).stem + ".txt")).exists() for r in images)
    projected = sam_image_cost(uncached)
    print(f"{args.split}: {len(images)} images, {uncached} uncached, projected ${projected:.3f}")
    if projected > args.max_usd:
        print(f"over the ${args.max_usd:.2f} limit; stopping")
        return 1
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    t0 = time.perf_counter()
    outputs = run_prompt(args.prompt, images, ledger)
    wall = time.perf_counter() - t0
    gt = ground_truth(images)
    result = dict(split=args.split, prompt=args.prompt, images=len(images),
                  gt_instances=sum(len(v) for v in gt.values()), new_calls=ledger.summary()["calls"],
                  usd=ledger.total(), wall_s=wall, scores=score_levels(outputs, gt))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"sam_{args.split}_{_slug(args.prompt)}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
