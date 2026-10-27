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


def score_levels(outputs: dict[str, str], gt: dict[str, list[np.ndarray]] | None = None, size: int = 640) -> dict:
    """Score raw SAM outputs (one text per image); see ``score_instances``."""
    return score_instances(list(outputs), lambda rel: parse_output(outputs[rel], size, size), gt, size)


def image_stats(truth_masks: list[np.ndarray], preds: list, size: int = 640) -> dict:
    """Per-image counts for every metric level; summed by ``aggregate`` (lets callers score in parallel)."""
    from benchmark.seg_metrics import match

    image = ImageResult("", truth_masks, [Prediction(i.mask, i.confidence or 0.0) for i in preds])
    inst = {}
    for thr in (0.5, 0.3):
        tp, fp, fn, ious = match(image, thr)
        inst[thr] = (tp, fp, fn, ious)
    pred = np.zeros((size, size), bool)
    for i in preds:
        pred |= i.mask
    truth = np.logical_or.reduce(truth_masks) if truth_masks else np.zeros((size, size), bool)
    tp, fp, fn = int((pred & truth).sum()), int((pred & ~truth).sum()), int((~pred & truth).sum())
    return dict(inst=inst, px=(tp, fp, fn), img_iou=tp / (tp + fp + fn) if tp + fp + fn else 1.0,
                has_pred=bool(preds), has_gt=bool(truth_masks), n_pred=len(preds), n_gt=len(truth_masks))


def aggregate(stats: list[dict]) -> dict:
    """Combine per-image stats into instance (IoU 0.5 and 0.3), pixel and image-level metrics."""
    instance = {}
    for thr in (0.5, 0.3):
        tp = sum(s["inst"][thr][0] for s in stats)
        fp = sum(s["inst"][thr][1] for s in stats)
        fn = sum(s["inst"][thr][2] for s in stats)
        ious = [v for s in stats for v in s["inst"][thr][3]]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        instance[f"iou>={thr}"] = dict(precision=p, recall=r, f1=2 * p * r / (p + r) if p + r else 0.0, tp=tp, fp=fp,
                                       fn=fn, mean_matched_iou=float(np.mean(ious)) if ious else 0.0)
    tp_px, fp_px, fn_px = (sum(s["px"][k] for s in stats) for k in range(3))
    pixel = dict(precision=tp_px / (tp_px + fp_px) if tp_px + fp_px else 0.0,
                 recall=tp_px / (tp_px + fn_px) if tp_px + fn_px else 0.0,
                 iou=tp_px / (tp_px + fp_px + fn_px) if tp_px + fp_px + fn_px else 0.0,
                 mean_image_iou=float(np.mean([s["img_iou"] for s in stats])))
    n = len(stats)
    annotated = sum(s["has_gt"] for s in stats)
    found = sum(s["has_pred"] for s in stats)
    both = sum(s["has_pred"] and s["has_gt"] for s in stats)
    image = dict(images=n, annotated=annotated, negatives=n - annotated, with_any_prediction=found,
                 detection_rate_on_positives=both / annotated if annotated else 0.0,
                 false_alarm_rate_on_negatives=((found - both) / (n - annotated)) if n - annotated else None)
    return dict(instance=instance, pixel=pixel, image=image,
                predictions_per_image=float(np.mean([s["n_pred"] for s in stats])),
                gt_instances_per_image=float(np.mean([s["n_gt"] for s in stats])),
                gt_instances=int(sum(s["n_gt"] for s in stats)))


def score_instances(images: list[str], predict, gt: dict[str, list[np.ndarray]] | None = None,
                    size: int = 640) -> dict:
    """Instance (IoU 0.5 and 0.3), pixel and image-level metrics, streamed one image at a time.

    ``predict(rel)`` returns the full-frame instances for an image. ``gt`` may
    be omitted; ground truth is then decoded per image, so memory stays
    bounded (masks for one image at a time).
    """
    return aggregate([image_stats(gt[rel] if gt is not None else ground_truth([rel])[rel], predict(rel), size)
                      for rel in images])


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
    scores = score_levels(outputs)
    result = dict(split=args.split, prompt=args.prompt, images=len(images), gt_instances=scores["gt_instances"],
                  new_calls=ledger.summary()["calls"], usd=ledger.total(), wall_s=wall, scores=scores)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"sam_{args.split}_{_slug(args.prompt)}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
