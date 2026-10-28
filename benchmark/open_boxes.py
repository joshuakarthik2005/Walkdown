"""On-prem box proposals: does adding open-weights boxes close the recall gap to Cloud mode?

On-prem mode had only the SAM 3.1 text prompt. This adds the Cloud pipeline's second perception path with open
weights only:
  1. Muse Spark Open (Baseten) proposes rust boxes on the full frame (same prompt as Cloud, JSON parsed from text);
  2. SAM 3.1 open weights (Modal) segment them: the boxes are visual exemplars, each keeps its best-overlapping
     detection (``Sam31.segment_boxes``);
  3. merged with the open-weights text masks by the same overlap merge as Cloud.

Variants (unverified candidates, scored with the sam_eval levels against the dataset masks):
  open_text, open_boxes, open_text_plus_boxes, and Cloud's cloud_text, cloud_text_plus_boxes from the hosted caches.
Caches under WALKDOWN_DATA_DIR/runs/open_boxes/ (and runs/sam_open/rust/ for the open text masks).

    .venv\\Scripts\\python.exe -m benchmark.open_boxes dev --max-usd 1
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.clients.cost import CostLedger
from backend.perception.boxes import propose_boxes
from backend.perception.sam import parse_output
from backend.perception.sam_open import segment_boxes_open, segment_images_open, to_instances
from backend.perception.tiling import merge_instances
from benchmark.box_prompt import CACHE as CLOUD_BOX_CACHE
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import RUN_DIR as CLOUD_SAM_DIR, ground_truth
from benchmark.sam_eval import aggregate, image_stats
from benchmark.splits import load_split

OPEN_TEXT = DATA_DIR / "runs" / "sam_open" / "rust"
CACHE = DATA_DIR / "runs" / "open_boxes"
LEDGER = DATA_DIR / "runs" / "cost_ledger.jsonl"
RESULTS = Path(__file__).parent / "results"
MODAL_BATCH = 50
THREADS = 8


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(images: list[str], ledger: CostLedger, max_usd: float) -> dict:
    """Fill the open-weights caches; returns per-image box-proposal latency and cost."""
    for d in (OPEN_TEXT, CACHE / "boxes", CACHE / "sam"):
        d.mkdir(parents=True, exist_ok=True)
    stem = lambda rel: Path(rel).stem  # noqa: E731
    todo = [rel for rel in images if not (OPEN_TEXT / f"{stem(rel)}.json").exists()]
    for i in range(0, len(todo), MODAL_BATCH):
        batch = todo[i:i + MODAL_BATCH]
        for rel, recs in zip(batch, segment_images_open([RAW_DIR / r for r in batch], "rust", ledger=ledger,
                                                        job="open-boxes-sam-text")):
            (OPEN_TEXT / f"{stem(rel)}.json").write_text(json.dumps(recs), encoding="utf-8")

    timing: dict[str, float] = {}

    def boxes_for(rel: str):
        path = CACHE / "boxes" / f"{stem(rel)}.json"
        if path.exists():
            return
        if ledger.total("open-boxes-propose") > max_usd:
            return
        t0 = time.perf_counter()
        boxes = propose_boxes(RAW_DIR / rel, 640, 640, ledger=ledger, job="open-boxes-propose", provider="baseten")
        timing[rel] = time.perf_counter() - t0
        path.write_text(json.dumps(boxes), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(boxes_for, images))
    todo = [rel for rel in images if (CACHE / "boxes" / f"{stem(rel)}.json").exists()
            and not (CACHE / "sam" / f"{stem(rel)}.json").exists()]
    for i in range(0, len(todo), MODAL_BATCH):
        batch = todo[i:i + MODAL_BATCH]
        boxes = [[tuple(b) for b in _json(CACHE / "boxes" / f"{stem(r)}.json")] for r in batch]
        for rel, recs in zip(batch, segment_boxes_open([RAW_DIR / r for r in batch], boxes, ledger=ledger,
                                                       job="open-boxes-sam-boxes")):
            (CACHE / "sam" / f"{stem(rel)}.json").write_text(json.dumps(recs), encoding="utf-8")
    return dict(propose_latency_s_median=statistics.median(timing.values()) if timing else None,
                new_proposals=len(timing))


def score(images: list[str]) -> dict:
    gt = ground_truth(images)
    stats: dict[str, list[dict]] = {k: [] for k in ("open_text", "open_boxes", "open_text_plus_boxes", "cloud_text",
                                                    "cloud_text_plus_boxes")}
    n_boxes, matched = 0, 0
    done = [rel for rel in images if (CACHE / "sam" / f"{Path(rel).stem}.json").exists()]
    for rel in done:
        s = Path(rel).stem
        o_text = to_instances(_json(OPEN_TEXT / f"{s}.json"), frame=0)
        o_box = to_instances(_json(CACHE / "sam" / f"{s}.json"), frame=0)
        n_boxes += len(_json(CACHE / "boxes" / f"{s}.json"))
        matched += len(o_box)
        c_text = parse_output((CLOUD_SAM_DIR / "rust" / f"{s}.txt").read_text(encoding="utf-8"), 640, 640)
        c_box_path = CLOUD_BOX_CACHE / "sam" / f"{s}.txt"
        c_box = parse_output(c_box_path.read_text(encoding="utf-8"), 640, 640) if c_box_path.exists() else []
        truth = gt.get(rel, [])
        for name, preds in (("open_text", o_text), ("open_boxes", o_box),
                            ("open_text_plus_boxes", merge_instances(o_text + o_box)),
                            ("cloud_text", c_text), ("cloud_text_plus_boxes", merge_instances(c_text + c_box))):
            stats[name].append(image_stats(truth, preds))
    out = {}
    for name, st in stats.items():
        a = aggregate(st)
        out[name] = dict(image_detection=a["image"]["detection_rate_on_positives"],
                         false_alarm_on_negatives=a["image"]["false_alarm_rate_on_negatives"],
                         pixel_recall=a["pixel"]["recall"], pixel_precision=a["pixel"]["precision"],
                         instance_iou05=a["instance"]["iou>=0.5"], predictions_per_image=a["predictions_per_image"])
    return dict(images_scored=len(done), boxes_proposed=n_boxes, boxes_with_open_mask=matched, variants=out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--max-images", type=int, default=None)
    ap.add_argument("--max-usd", type=float, default=1.0, help="cap on new Baseten box-proposal spend")
    args = ap.parse_args()
    images = load_split(args.split)[:args.max_images]
    ledger = CostLedger(LEDGER)
    info = run(images, ledger, args.max_usd)
    result = dict(split=args.split, images=len(images), **info,
                  usd=dict(propose=ledger.total("open-boxes-propose"),
                           modal=ledger.total("open-boxes-sam-text") + ledger.total("open-boxes-sam-boxes")),
                  **score(images))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"open_boxes_{args.split}.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
