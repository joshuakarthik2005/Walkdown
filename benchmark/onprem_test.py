"""On-prem mode on the full test split (1,444 images), verified: open-weights perception + Muse Spark Open verifier.

Pipeline (open weights only, as the product's On-prem mode):
  1. SAM 3.1 open weights (Modal) with the text prompt "rust"            -> runs/sam_open/rust/<stem>.json
  2. Muse Spark Open box proposals (Fireworks serverless; same model as Baseten, 97% identical decisions, RESULTS 6)
                                                                          -> runs/open_boxes_fw/boxes/<stem>.json
  3. SAM 3.1 open weights segment the boxes as exemplars (Modal)         -> runs/open_boxes_fw/sam/<stem>.json
  4. merge text + boxes, verify every merged candidate with Muse Spark Open (Fireworks serverless, max_tokens 8,000)
                                                                          -> runs/verify/fireworks/onprem/<id>.json
Scoring per image (sam_eval levels) for: open text only, open text + boxes, open text + boxes + verifier; the Cloud
pipeline's verified text + boxes on the same images comes from the box_verify journal (RESULTS 4).

Images are processed in a seeded random order with a hard spend cap, so a stopped run is an unbiased sample.
Resumable (journal per image).

    .venv\\Scripts\\python.exe -m benchmark.onprem_test --max-usd 82
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from backend.clients.cost import CostLedger
from backend.perception.boxes import FIREWORKS_SPARK_OPEN, merge_with_text, propose_boxes
from backend.perception.sam_open import segment_boxes_open, segment_images_open, to_instances
from backend.verify.schema import Grade
from backend.verify.verifier import Candidate, verify
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import ground_truth
from benchmark.sam_eval import aggregate, image_stats
from benchmark.splits import load_split

TEXT = DATA_DIR / "runs" / "sam_open" / "rust"
BOXES = DATA_DIR / "runs" / "open_boxes_fw"
VERDICTS = DATA_DIR / "runs" / "verify" / "fireworks" / "onprem"
JOURNAL = DATA_DIR / "runs" / "onprem_test_journal.jsonl"
CLOUD_JOURNAL = DATA_DIR / "runs" / "box_verify_test_journal.jsonl"
RESULT = Path(__file__).parent / "results" / "onprem_test.json"
MODAL_BATCH, THREADS, SEED = 50, 16, 20261029
VARIANTS = ("open_text", "open_text_plus_boxes", "open_text_plus_boxes_verified")


def _stem(rel: str) -> str:
    return Path(rel).stem


def stage_text(images: list[str], ledger: CostLedger) -> None:
    TEXT.mkdir(parents=True, exist_ok=True)
    todo = [r for r in images if not (TEXT / f"{_stem(r)}.json").exists()]
    for i in range(0, len(todo), MODAL_BATCH):
        b = todo[i:i + MODAL_BATCH]
        for rel, recs in zip(b, segment_images_open([RAW_DIR / r for r in b], "rust", ledger=ledger, job="onprem-test-sam-text")):
            (TEXT / f"{_stem(rel)}.json").write_text(json.dumps(recs), encoding="utf-8")
        print(f"text {i + len(b)}/{len(todo)}", flush=True)


def stage_boxes(images: list[str], ledger: CostLedger, cap: float) -> None:
    (BOXES / "boxes").mkdir(parents=True, exist_ok=True)

    def one(rel: str) -> None:
        path = BOXES / "boxes" / f"{_stem(rel)}.json"
        if path.exists() or ledger.total() > cap:
            return
        path.write_text(json.dumps(propose_boxes(RAW_DIR / rel, 640, 640, ledger=ledger, job="onprem-test-propose",
                                                 provider="fireworks")), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(one, images))
    (BOXES / "sam").mkdir(parents=True, exist_ok=True)
    todo = [r for r in images if (BOXES / "boxes" / f"{_stem(r)}.json").exists()
            and not (BOXES / "sam" / f"{_stem(r)}.json").exists()]
    for i in range(0, len(todo), MODAL_BATCH):
        b = todo[i:i + MODAL_BATCH]
        bx = [[tuple(x) for x in json.loads((BOXES / "boxes" / f"{_stem(r)}.json").read_text(encoding="utf-8"))] for r in b]
        for rel, recs in zip(b, segment_boxes_open([RAW_DIR / r for r in b], bx, ledger=ledger, job="onprem-test-sam-boxes")):
            (BOXES / "sam" / f"{_stem(rel)}.json").write_text(json.dumps(recs), encoding="utf-8")
        print(f"box masks {i + len(b)}/{len(todo)}", flush=True)


def _accepted(path: Path) -> bool:
    g = json.loads(path.read_text(encoding="utf-8"))["grade"]
    return Grade.model_validate(g).is_defect if g else True  # invalid replies fail open


def verify_image(rel: str, ledger: CostLedger, cap: float) -> dict | None:
    s = _stem(rel)
    if not (BOXES / "sam" / f"{s}.json").exists():
        return None
    text = to_instances(json.loads((TEXT / f"{s}.json").read_text(encoding="utf-8")), frame=0)
    box = to_instances(json.loads((BOXES / "sam" / f"{s}.json").read_text(encoding="utf-8")), frame=0)
    merged = merge_with_text(text, box)
    img = cv2.imread(str(RAW_DIR / rel), cv2.IMREAD_COLOR)
    VERDICTS.mkdir(parents=True, exist_ok=True)
    keep, invalid = [], 0
    for obj, inst in merged:
        path = VERDICTS / f"{s}__{obj}.json"
        if not path.exists():
            if ledger.total() > cap:
                return None
            v = verify(Candidate(f"{s}#{obj}", img, inst.mask, inst.box, inst.confidence,
                                 source="box" if obj.startswith("b") else "text"),
                       provider="fireworks", model=FIREWORKS_SPARK_OPEN, ledger=ledger, job="onprem-test-verify")
            d = asdict(v)
            d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
            path.write_text(json.dumps(d), encoding="utf-8")
        invalid += json.loads(path.read_text(encoding="utf-8"))["grade"] is None
        if _accepted(path):
            keep.append(inst)
    truth = ground_truth([rel])[rel]
    return dict(image=rel, candidates=len(merged), accepted=len(keep), invalid=invalid,
                stats={"open_text": image_stats(truth, text),
                       "open_text_plus_boxes": image_stats(truth, [i for _, i in merged]),
                       "open_text_plus_boxes_verified": image_stats(truth, keep)})


def summarise(rows: list[dict]) -> dict:
    cloud = {}
    if CLOUD_JOURNAL.exists():
        for line in CLOUD_JOURNAL.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            cloud[r["image"]] = r["stats"]
    def fix(st: dict) -> dict:  # json turned the IoU-threshold keys into strings
        st = dict(st)
        st["inst"] = {float(k): v for k, v in st["inst"].items()}
        return st
    out = {v: aggregate([fix(r["stats"][v]) for r in rows]) for v in VARIANTS}
    both = [r for r in rows if r["image"] in cloud]
    for v in ("text_plus_boxes", "text_plus_boxes_verified"):
        out[f"cloud_{v}_same_images"] = aggregate([fix(cloud[r["image"]][v]) for r in both]) if both else None
    n_c = sum(r["candidates"] for r in rows)
    return dict(images=len(rows), candidates=n_c, accepted=sum(r["accepted"] for r in rows),
                invalid_reply_rate=sum(r["invalid"] for r in rows) / n_c if n_c else None,
                cloud_comparison_images=len(both), variants=out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-usd", type=float, required=True, help="cap on new Fireworks + Modal spend in this run")
    ap.add_argument("--stage", choices=("all", "perception", "verify", "summary"), default="all")
    ap.add_argument("--limit", type=int, default=None, help="first N images of the shuffled order (dry run)")
    args = ap.parse_args()
    images = load_split("test")
    random.Random(SEED).shuffle(images)  # a budget stop leaves a random sample
    images = images[:args.limit]
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    if args.stage in ("all", "perception"):
        stage_text(images, ledger)
        stage_boxes(images, ledger, args.max_usd)
    if args.stage in ("all", "verify"):
        done = {json.loads(l)["image"] for l in JOURNAL.read_text(encoding="utf-8").splitlines()} if JOURNAL.exists() else set()
        lock, t0 = threading.Lock(), time.time()
        count = [0]

        def one(rel: str) -> None:
            if rel in done or ledger.total() > args.max_usd:
                return
            r = verify_image(rel, ledger, args.max_usd)
            if r is None:
                return
            with lock:
                with JOURNAL.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(r) + "\n")
                count[0] += 1
                if count[0] % 25 == 0:
                    print(f"verified {count[0]} images, ${ledger.total():.2f}, {(time.time() - t0) / 60:.0f} min", flush=True)

        with ThreadPoolExecutor(max_workers=THREADS) as pool:  # one image per worker, its candidates in sequence
            list(pool.map(one, images))
    rows = [json.loads(l) for l in JOURNAL.read_text(encoding="utf-8").splitlines()] if JOURNAL.exists() else []
    res = dict(new_usd=round(ledger.total(), 3), **summarise(rows))
    RESULT.parent.mkdir(exist_ok=True)
    RESULT.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "variants"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
