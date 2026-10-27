"""Recall experiment (dev only): Muse Spark proposes rust boxes, SAM 3.1 segments inside them.

Per image:
  1. Muse Spark (minimal reasoning, strict JSON) looks at the full 640x640 frame and lists up to 16 boxes
     around visible rust or corrosion, in pixel coordinates.
  2. SAM 3.1 gets those boxes as object prompts (``meta_sam_parser.build_object_prompt``; box prompts and a
     text concept cannot be mixed in one request) and returns one mask per box.
  3. Box masks are merged with the cached text-prompt ("rust") masks using the same overlap merge as tiling.
Variants scored with the same levels as sam_eval: text only (baseline), boxes only, text + boxes.
Raw outputs are cached under WALKDOWN_DATA_DIR/runs/box_prompt/.

    .venv\\Scripts\\python.exe -m benchmark.box_prompt dev --max-usd 1
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import meta_sam_parser as msp
from pydantic import BaseModel, Field

from backend.clients.cost import CostEntry, CostLedger, muse_cost
from backend.clients.meta import meta_client, with_retries
from backend.perception.sam import parse_output, segment_image
from backend.perception.tiling import merge_instances
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR
from benchmark.sam_dryrun import ground_truth
from benchmark.sam_eval import aggregate, image_stats
from benchmark.splits import load_split

CACHE = DATA_DIR / "runs" / "box_prompt"
RESULTS = Path(__file__).parent / "results"
SIZE = 640
MAX_BOXES = 16  # SAM 3.1 object-prompt limit

BOX_SYSTEM = (f"You find corrosion on industrial and outdoor metal. The image is {SIZE}x{SIZE} pixels. "
              f"List a tight bounding box around every separate visible rust or corrosion region (orange-brown "
              f"oxide, flaking, pitting, rust staining), at most {MAX_BOXES}, largest first. Coordinates are "
              f"integer pixels: left, top, right, bottom, with 0 <= left < right <= {SIZE} and "
              f"0 <= top < bottom <= {SIZE}. Return an empty list if there is no corrosion.")


class Box(BaseModel):
    left: int = Field(ge=0, le=SIZE)
    top: int = Field(ge=0, le=SIZE)
    right: int = Field(ge=0, le=SIZE)
    bottom: int = Field(ge=0, le=SIZE)


class Boxes(BaseModel):
    boxes: list[Box]


SCHEMA = {"type": "object", "additionalProperties": False, "required": ["boxes"], "properties": {
    "boxes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["left", "top", "right", "bottom"],
                                         "properties": {k: {"type": "integer"} for k in
                                                        ("left", "top", "right", "bottom")}}}}}


def propose_boxes(rel: str, ledger: CostLedger) -> list[Box]:
    """Muse Spark box proposals for one image (cached)."""
    path = CACHE / "boxes" / (Path(rel).stem + ".json")
    if path.exists():
        return Boxes.model_validate_json(path.read_text(encoding="utf-8")).boxes
    url = "data:image/jpeg;base64," + base64.b64encode((RAW_DIR / rel).read_bytes()).decode()
    resp = with_retries(lambda: meta_client().chat.completions.create(
        model="muse-spark-1.3", reasoning_effort="minimal", max_tokens=3000,
        response_format={"type": "json_schema", "json_schema": {"name": "boxes", "strict": True, "schema": SCHEMA}},
        messages=[{"role": "system", "content": BOX_SYSTEM},
                  {"role": "user", "content": [{"type": "text", "text": "Find the corrosion."},
                                               {"type": "image_url", "image_url": {"url": url}}]}]))
    u = resp.usage
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    ledger.add(CostEntry(job="box-propose", model="muse-spark-1.3", usd=muse_cost(u.prompt_tokens, u.completion_tokens, cached),
                         input_tokens=u.prompt_tokens, cached_tokens=cached, output_tokens=u.completion_tokens))
    raw = Boxes.model_validate_json(resp.choices[0].message.content or '{"boxes": []}')
    boxes = [b for b in raw.boxes if b.right - b.left >= 4 and b.bottom - b.top >= 4][:MAX_BOXES]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(Boxes(boxes=boxes).model_dump_json(), encoding="utf-8")
    return boxes


def box_masks(rel: str, boxes: list[Box], ledger: CostLedger):
    """SAM 3.1 masks for box prompts on one image (cached)."""
    if not boxes:
        return []
    path = CACHE / "sam" / (Path(rel).stem + ".txt")
    if not path.exists():
        prompt = msp.build_object_prompt(size=(SIZE, SIZE), objects=[
            msp.PromptObject(id=i, prompts=[msp.FramePrompt(frame=0, box=msp.PromptBox(b.left, b.top, b.right, b.bottom))])
            for i, b in enumerate(boxes)])
        res = segment_image(RAW_DIR / rel, prompt, size=(SIZE, SIZE), ledger=ledger, job="box-sam")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(res.raw_output, encoding="utf-8")
    return parse_output(path.read_text(encoding="utf-8"), SIZE, SIZE)


VARIANTS = ("text_only", "boxes_only", "text_plus_boxes")


def variant_stats(rel: str) -> dict:
    """Per-image stats for all three variants, decoding each mask once (runs in a worker process)."""
    text = parse_output((SAM_DIR / "rust" / (Path(rel).stem + ".txt")).read_text(encoding="utf-8"), SIZE, SIZE)
    path = CACHE / "sam" / (Path(rel).stem + ".txt")
    boxes = parse_output(path.read_text(encoding="utf-8"), SIZE, SIZE) if path.exists() else []
    truth = ground_truth([rel])[rel]
    return {"text_only": image_stats(truth, merge_instances(text)),
            "boxes_only": image_stats(truth, merge_instances(boxes)),
            "text_plus_boxes": image_stats(truth, merge_instances(text + boxes))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--score-workers", type=int, default=6)
    args = ap.parse_args()
    images = load_split(args.split)
    uncached = sum(not (CACHE / "boxes" / (Path(r).stem + ".json")).exists() for r in images)
    est = uncached * (0.0025 + 0.003)  # SAM call + one minimal Muse Spark call (dry-run estimate)
    print(f"{args.split}: {len(images)} images, {uncached} uncached, estimated ${est:.2f}", flush=True)
    if est > args.max_usd:
        print("over the limit; stopping")
        return 1
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")

    def fetch(rel: str) -> int:  # API part only: boxes + SAM box masks, cached
        boxes = propose_boxes(rel, ledger)
        if boxes and not (CACHE / "sam" / (Path(rel).stem + ".txt")).exists():
            box_masks(rel, boxes, ledger)
        return len(boxes)

    with ThreadPoolExecutor(max_workers=8) as pool:
        n_boxes = list(pool.map(fetch, images))
    print(f"API part done: new ${ledger.total():.3f} (boxes ${ledger.total('box-propose'):.3f}, "
          f"SAM ${ledger.total('box-sam'):.3f})", flush=True)
    # Scoring decodes every mask once per image (pure-Python decoder), in worker processes.
    with ProcessPoolExecutor(max_workers=args.score_workers) as pool:
        per_image = list(pool.map(variant_stats, images, chunksize=4))
    out = dict(split=args.split, images=len(images), boxes_per_image=sum(n_boxes) / len(images),
               images_with_boxes=sum(n > 0 for n in n_boxes), new_usd=ledger.total(),
               usd_by_job={j: ledger.total(j) for j in ("box-propose", "box-sam")},
               variants={k: aggregate([s[k] for s in per_image]) for k in VARIANTS})
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"box_prompt_{args.split}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"boxes/image {out['boxes_per_image']:.2f}, images with boxes {out['images_with_boxes']}, new ${ledger.total():.3f}")
    for k, s in out["variants"].items():
        i = s["instance"]["iou>=0.5"]
        print(f"{k:16} img-det {s['image']['detection_rate_on_positives']:.3f} | pixel P {s['pixel']['precision']:.3f} "
              f"R {s['pixel']['recall']:.3f} | inst P {i['precision']:.3f} R {i['recall']:.3f} F1 {i['f1']:.3f} | "
              f"cands/img {s['predictions_per_image']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
