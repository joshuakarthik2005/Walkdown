"""SAM 3.1 dry run on the dev split: compare text prompts before scaling up.

For each prompt, every dev image is segmented once; the raw SAM output is
cached under ``<WALKDOWN_DATA_DIR>/runs/sam/<prompt>/`` so re-scoring is free.
Scores (instance level, IoU >= 0.5, at several confidence thresholds) and the
measured cost are written to benchmark/results/sam_dryrun_dev.json.
Dataset images never leave WALKDOWN_DATA_DIR (see DECISIONS.md: scoring only).

    .venv\\Scripts\\python.exe -m benchmark.sam_dryrun rust corrosion "corroded metal"
"""

from __future__ import annotations

import json
import re
import sys
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from pycocotools import mask as mask_utils

from backend.clients.cost import CostLedger, sam_image_cost
from backend.perception.sam import parse_output, segment_image
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.seg_metrics import ImageResult, Prediction, evaluate
from benchmark.splits import load_split

RUN_DIR = DATA_DIR / "runs" / "sam"
RESULTS = Path(__file__).parent / "results" / "sam_dryrun_dev.json"
THRESHOLDS = (0.0, 0.3, 0.5, 0.7)
MAX_USD = 1.00  # guard for this dry run


@lru_cache(maxsize=4)
def _coco_index(split: str) -> tuple[dict, dict]:
    """(images by relative path, annotations by image id) for one dataset folder, parsed once."""
    coco = json.loads((RAW_DIR / split / "_annotations.coco.json").read_text(encoding="utf-8"))
    images = {f"{split}/{i['file_name']}": i for i in coco["images"]}
    by_id: dict[int, list] = {}
    for a in coco["annotations"]:
        by_id.setdefault(a["image_id"], []).append(a)
    return images, by_id


def ground_truth(rel_paths: list[str]) -> dict[str, list[np.ndarray]]:
    """Ground-truth instance masks per image, decoded from the COCO polygons."""
    out: dict[str, list[np.ndarray]] = {}
    for split in sorted({p.split("/")[0] for p in rel_paths}):
        images, by_id = _coco_index(split)
        for rel in rel_paths:
            if rel in images:
                img = images[rel]
                h, w = img["height"], img["width"]
                out[rel] = [mask_utils.decode(mask_utils.merge(mask_utils.frPyObjects(a["segmentation"], h, w)))
                            .astype(bool) for a in by_id.get(img["id"], [])]
    return out


def _slug(prompt: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")


def run_prompt(prompt: str, images: list[str], ledger: CostLedger) -> dict[str, str]:
    """Raw SAM output per image, from cache where available."""
    cache = RUN_DIR / _slug(prompt)
    cache.mkdir(parents=True, exist_ok=True)

    def one(rel: str) -> tuple[str, str]:
        path = cache / (Path(rel).stem + ".txt")
        if path.exists():
            return rel, path.read_text(encoding="utf-8")
        res = segment_image(RAW_DIR / rel, prompt, size=(640, 640), ledger=ledger, job=f"sam-dryrun-{_slug(prompt)}")
        path.write_text(res.raw_output, encoding="utf-8")
        return rel, res.raw_output

    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, images))


def score(outputs: dict[str, str], gt: dict[str, list[np.ndarray]]) -> dict:
    """Instance metrics at each confidence threshold, plus pixel-level IoU of the union masks."""
    parsed = {rel: parse_output(text, 640, 640) for rel, text in outputs.items()}
    rows = {}
    for t in THRESHOLDS:
        images = [ImageResult(rel, gt[rel], [Prediction(i.mask, i.confidence or 0.0) for i in parsed[rel]
                                             if (i.confidence or 0.0) >= t]) for rel in outputs]
        m = evaluate(images)
        pixel = []
        for rel in outputs:
            pred = np.zeros((640, 640), bool)
            for i in parsed[rel]:
                if (i.confidence or 0.0) >= t:
                    pred |= i.mask
            truth = np.logical_or.reduce(gt[rel]) if gt[rel] else np.zeros((640, 640), bool)
            union = (pred | truth).sum()
            pixel.append((pred & truth).sum() / union if union else 1.0)
        rows[f"conf>={t}"] = dict(precision=m.precision, recall=m.recall, f1=m.f1, tp=m.tp, fp=m.fp, fn=m.fn,
                                  mean_matched_iou=m.mean_matched_iou, pixel_iou=float(np.mean(pixel)),
                                  predictions_per_image=(m.tp + m.fp) / len(images))
    return rows


def main(prompts: list[str]) -> int:
    dev = load_split("dev")
    projected = sum(sum(not (RUN_DIR / _slug(p) / (Path(r).stem + ".txt")).exists() for r in dev) for p in prompts)
    print(f"{len(dev)} dev images x {len(prompts)} prompts; {projected} uncached calls, "
          f"projected ${sam_image_cost(projected):.3f}")
    if sam_image_cost(projected) > MAX_USD:
        print(f"over the ${MAX_USD:.2f} guard; stopping")
        return 1
    gt = ground_truth(dev)
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    results = {"split": "dev", "images": len(dev), "gt_instances": sum(len(v) for v in gt.values()),
               "iou_threshold": 0.5, "prompts": {}}
    for prompt in prompts:
        t0 = time.perf_counter()
        outputs = run_prompt(prompt, dev, ledger)
        results["prompts"][prompt] = dict(scores=score(outputs, gt), wall_s=time.perf_counter() - t0,
                                          new_calls=ledger.summary(f"sam-dryrun-{_slug(prompt)}")["calls"],
                                          usd=ledger.total(f"sam-dryrun-{_slug(prompt)}"))
        s = results["prompts"][prompt]["scores"]["conf>=0.5"]
        print(f"{prompt!r:18} P {s['precision']:.2f} R {s['recall']:.2f} F1 {s['f1']:.2f} "
              f"pixIoU {s['pixel_iou']:.2f} preds/img {s['predictions_per_image']:.1f} "
              f"${results['prompts'][prompt]['usd']:.3f}", flush=True)
    results["usd_total_this_run"] = ledger.total()
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {RESULTS}; spent ${ledger.total():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["rust", "corrosion", "corroded metal"]))
