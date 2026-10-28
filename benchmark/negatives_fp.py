"""False alarms on images with no corrosion, for both modes and every pipeline stage.

Input: a folder of negative images (public set: ``negatives_public/images``; the builder's set later). Each set is
reported on its own. For every image and mode:

- Cloud: hosted SAM 3.1 text prompt "rust"; Muse Spark box proposals (minimal effort) segmented by hosted SAM 3.1;
  merge; Muse Spark verifier at the live-demo effort (minimal).
- On-prem: SAM 3.1 open weights on Modal (text prompt, threshold 0.5); Muse Spark Open box proposals segmented by
  the open weights (box exemplars); merge; Muse Spark Open verifier.

Metric: the share of images with at least one candidate (text only, text + boxes) and with at least one candidate
the verifier accepts (text + boxes + verifier: what the register would show), plus candidates per image. Invalid
verifier replies count as accepted (fail open, as in the product). Raw outputs are cached under
WALKDOWN_DATA_DIR/runs/negatives_fp/<set>/.

    .venv\\Scripts\\python.exe -m benchmark.negatives_fp public --mode cloud --limit 20 --max-usd 0.5
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import cv2

from backend.clients.cost import CostLedger
from backend.perception.boxes import box_masks, merge_with_text, parse_box_output, propose_boxes
from backend.perception.sam import parse_output, segment_image
from backend.perception.sam_open import segment_boxes_open, segment_images_open, to_instances
from backend.verify.schema import Grade
from backend.verify.verifier import Candidate, Verdict, verify
from benchmark.download_dataset import DATA_DIR

SETS = {"public": DATA_DIR / "negatives_public" / "images", "builder": DATA_DIR / "negatives" / "frames"}
RESULTS = Path(__file__).parent / "results"
LEDGER = DATA_DIR / "runs" / "cost_ledger.jsonl"
THREADS = 8
MODAL_BATCH = 50


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _verdict(path: Path, cand: Candidate, provider: str, effort: str, ledger: CostLedger) -> bool:
    """Accepted? (cached; invalid replies fail open)."""
    if path.exists():
        g = _read(path)["grade"]
    else:
        v: Verdict = verify(cand, provider=provider, reasoning_effort=effort, ledger=ledger, job=f"negatives-fp-{provider}")
        d = asdict(v)
        d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
        _write(path, d)
        g = d["grade"]
    return Grade.model_validate(g).is_defect if g else True


def run(images: list[Path], mode: str, cache: Path, ledger: CostLedger, max_usd: float) -> list[dict]:
    over = lambda: ledger.total() > max_usd  # noqa: E731
    sizes = {p: cv2.imread(str(p)).shape[:2] for p in images}
    if mode == "on-prem":  # batch the Modal calls
        todo = [p for p in images if not (cache / "text" / f"{p.stem}.json").exists()]
        for i in range(0, len(todo), MODAL_BATCH):
            for p, recs in zip(todo[i:i + MODAL_BATCH], segment_images_open(todo[i:i + MODAL_BATCH], "rust",
                                                                             ledger=ledger, job="negatives-fp-sam-open")):
                _write(cache / "text" / f"{p.stem}.json", recs)

    def boxes(p: Path) -> None:
        path = cache / "boxes" / f"{p.stem}.json"
        if path.exists() or over():
            return
        h, w = sizes[p]
        _write(path, propose_boxes(p, w, h, ledger=ledger, job=f"negatives-fp-boxes-{mode}",
                                   provider="baseten" if mode == "on-prem" else "meta"))

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(boxes, images))
    ready = [p for p in images if (cache / "boxes" / f"{p.stem}.json").exists()]
    if mode == "on-prem":
        todo = [p for p in ready if not (cache / "box_masks" / f"{p.stem}.json").exists()]
        for i in range(0, len(todo), MODAL_BATCH):
            batch = todo[i:i + MODAL_BATCH]
            bxs = [[tuple(b) for b in _read(cache / "boxes" / f"{p.stem}.json")] for p in batch]
            for p, recs in zip(batch, segment_boxes_open(batch, bxs, ledger=ledger, job="negatives-fp-box-sam-open")):
                _write(cache / "box_masks" / f"{p.stem}.json", recs)

    def one(p: Path) -> dict | None:
        h, w = sizes[p]
        if mode == "cloud":
            tpath, bpath = cache / "text" / f"{p.stem}.txt", cache / "box_masks" / f"{p.stem}.txt"
            if not tpath.exists():
                if over():
                    return None
                tpath.parent.mkdir(parents=True, exist_ok=True)
                tpath.write_text(segment_image(p, "rust", ledger=ledger, job="negatives-fp-sam").raw_output,
                                 encoding="utf-8")
            if not bpath.exists():
                if over():
                    return None
                bpath.parent.mkdir(parents=True, exist_ok=True)
                bpath.write_text(box_masks(p, [tuple(b) for b in _read(cache / "boxes" / f"{p.stem}.json")], w, h,
                                           ledger=ledger, job="negatives-fp-box-sam"), encoding="utf-8")
            text = parse_output(tpath.read_text(encoding="utf-8"), w, h)
            box = parse_box_output(bpath.read_text(encoding="utf-8"), w, h)
            provider, effort = "meta", "minimal"
        else:
            if not (cache / "box_masks" / f"{p.stem}.json").exists():
                return None
            text = to_instances(_read(cache / "text" / f"{p.stem}.json"), frame=0)
            box = to_instances(_read(cache / "box_masks" / f"{p.stem}.json"), frame=0)
            provider, effort = "baseten", "low"
        merged = merge_with_text(text, box)
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        accepted = 0
        for obj, inst in merged:
            path = cache / "verify" / f"{p.stem}__{obj}.json"
            if not path.exists() and over():
                return None
            accepted += _verdict(path, Candidate(f"{p.stem}#{obj}", img, inst.mask, inst.box, inst.confidence),
                                 provider, effort, ledger)
        return dict(image=p.name, text=len(text), merged=len(merged), accepted=accepted)

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        return [r for r in pool.map(one, ready) if r is not None]


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    share = lambda k: sum(r[k] > 0 for r in rows) / n if n else None  # noqa: E731
    mean = lambda k: sum(r[k] for r in rows) / n if n else None  # noqa: E731
    return dict(images=n, images_with_alarm=dict(text_only=share("text"), text_plus_boxes=share("merged"),
                                                 text_plus_boxes_verified=share("accepted")),
                candidates_per_image=dict(text_only=mean("text"), text_plus_boxes=mean("merged"),
                                          accepted=mean("accepted")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("set", choices=sorted(SETS))
    ap.add_argument("--mode", choices=("cloud", "on-prem"), required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-usd", type=float, required=True)
    args = ap.parse_args()
    images = sorted(p for p in SETS[args.set].iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[:args.limit]
    ledger = CostLedger(LEDGER)
    rows = run(images, args.mode, DATA_DIR / "runs" / "negatives_fp" / args.set / args.mode, ledger, args.max_usd)
    out = dict(set=args.set, mode=args.mode, images_requested=len(images), new_usd=ledger.total(),
               **summarise(rows), rows=rows)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"negatives_fp_{args.set}_{args.mode}.json").write_text(json.dumps(out, indent=1) + "\n",
                                                                       encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
