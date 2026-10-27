"""Recall experiment: tiled SAM 3.1 and prompt unions, scored on a split (dev for tuning).

Variants: ``--grid 1|2|3`` (n x n tiles, 15% overlap) and ``--prompts`` (one or
more concept prompts, unioned and merged). Raw outputs are cached per tile
and prompt on WALKDOWN_DATA_DIR, so re-scoring is free. Scores use the same
levels as sam_eval (instance at IoU 0.5 and 0.3, pixel, image) plus
candidates per image and cost per image.

    .venv\\Scripts\\python.exe -m benchmark.sam_tiling dev --grid 2 --prompts rust --max-usd 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from backend.clients.cost import CostLedger, sam_image_cost
from backend.perception.sam import parse_output, segment_image
from backend.perception.tiling import segment_tiled, tile_boxes
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR, _slug, ground_truth
from benchmark.sam_eval import score_instances
from benchmark.splits import load_split

TILE_DIR = DATA_DIR / "runs" / "sam_tiled"
RESULTS_DIR = Path(__file__).parent / "results"


def variant_name(grid: int, prompts: list[str]) -> str:
    return f"grid{grid}_{'+'.join(_slug(p) for p in prompts)}"


def cache_path(rel: str, prompt: str, grid: int, tile: int) -> Path:
    if grid == 1:  # reuse the untiled cache from the main SAM runs
        return SAM_DIR / _slug(prompt) / (Path(rel).stem + ".txt")
    return TILE_DIR / f"grid{grid}" / _slug(prompt) / f"{Path(rel).stem}_t{tile}.txt"


def predict(rel: str, grid: int, prompts: list[str], ledger: CostLedger, job: str):
    image = cv2.imread(str(RAW_DIR / rel), cv2.IMREAD_COLOR)

    def tile_call(png: bytes, prompt: str, size: tuple[int, int], t: int):
        path = cache_path(rel, prompt, grid, t)
        if path.exists():
            return parse_output(path.read_text(encoding="utf-8"), *size)
        res = segment_image(png, prompt, size=size, ledger=ledger, job=job)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(res.raw_output, encoding="utf-8")
        return res.instances

    return segment_tiled(image, prompts, grid, tile_call)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--grid", type=int, default=2)
    ap.add_argument("--prompts", nargs="+", default=["rust"])
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    images = load_split(args.split)
    calls_per_image = len(tile_boxes(640, 640, args.grid)) * len(args.prompts)
    uncached = sum(not cache_path(r, p, args.grid, t).exists() for r in images for p in args.prompts
                   for t in range(len(tile_boxes(640, 640, args.grid))))
    print(f"{variant_name(args.grid, args.prompts)} on {args.split}: {len(images)} images, {calls_per_image} calls/image, "
          f"{uncached} uncached, projected ${sam_image_cost(uncached):.2f}", flush=True)
    if sam_image_cost(uncached) > args.max_usd:
        print("over the limit; stopping")
        return 1
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    job = f"sam-tiled-{variant_name(args.grid, args.prompts)}"
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:  # API-bound; decoding is per tile
        preds = dict(zip(images, pool.map(lambda r: predict(r, args.grid, args.prompts, ledger, job), images)))
    scores = score_instances(images, lambda rel: preds[rel])
    result = dict(split=args.split, variant=variant_name(args.grid, args.prompts), grid=args.grid, prompts=args.prompts,
                  images=len(images), calls_per_image=calls_per_image,
                  cost_per_image=sam_image_cost(calls_per_image), new_usd=ledger.total(),
                  wall_s=time.perf_counter() - t0, scores=scores)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"sam_tiling_{args.split}_{result['variant']}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    s = scores
    print(f"img-det {s['image']['detection_rate_on_positives']:.3f} | pixel P {s['pixel']['precision']:.3f} "
          f"R {s['pixel']['recall']:.3f} IoU {s['pixel']['iou']:.3f} | inst@0.5 P {s['instance']['iou>=0.5']['precision']:.3f} "
          f"R {s['instance']['iou>=0.5']['recall']:.3f} F1 {s['instance']['iou>=0.5']['f1']:.3f} | "
          f"cands/img {s['predictions_per_image']:.2f} | ${result['cost_per_image']:.4f}/img | new ${ledger.total():.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
