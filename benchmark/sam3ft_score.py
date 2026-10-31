"""Score SAM 3 (base / fine-tuned, from modal_apps/sam3_finetune.py) against SAM 3.1 on the 50 dev images.

Text prompt "rust" only, same metrics as sam_eval (image detection, pixel P/R/IoU, instance P/R/F1 at IoU 0.5).
Baselines from the existing caches: SAM 3.1 open weights (runs/sam_open/rust) and hosted SAM 3.1
(runs/sam_dryrun/rust).

    .venv\\Scripts\\python.exe -m benchmark.sam3ft_score base smoke
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pycocotools import mask as mask_utils

from backend.perception.sam import Instance, parse_output
from backend.perception.sam_open import to_instances
from benchmark.download_dataset import DATA_DIR
from benchmark.sam_dryrun import RUN_DIR as HOSTED_DIR, ground_truth
from benchmark.sam_eval import aggregate, image_stats
from benchmark.splits import load_split

RES = DATA_DIR / "sam3ft" / "results"
OUT = Path(__file__).parent / "results" / "sam3ft_dev.json"


def fetch(tag: str) -> Path:
    RES.mkdir(parents=True, exist_ok=True)
    dst = RES / f"eval_{tag}.json"
    if not dst.exists():
        subprocess.run([str(Path(sys.executable).parent / "modal.exe"), "volume", "get", "--force", "walkdown-sam3ft",
                        f"/results/eval_{tag}.json", str(dst)], check=True, env={**__import__("os").environ,
                                                                                 "MSYS_NO_PATHCONV": "1"})
    return dst


def sam3_instances(recs: list[dict]) -> list[Instance]:
    out = []
    for k, r in enumerate(recs):
        rle = {"size": r["rle"]["size"], "counts": r["rle"]["counts"].encode()}
        m = mask_utils.decode(rle).astype(bool)
        if m.any():
            ys, xs = m.nonzero()
            out.append(Instance(object_id=str(k), box=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
                                mask=m, confidence=r["score"]))
    return out


def summary(stats: list[dict]) -> dict:
    a = aggregate(stats)
    i = a["instance"]["iou>=0.5"]
    return dict(image_detection=a["image"]["detection_rate_on_positives"], pixel_precision=a["pixel"]["precision"],
                pixel_recall=a["pixel"]["recall"], pixel_iou=a["pixel"]["iou"], instance_p=i["precision"],
                instance_r=i["recall"], instance_f1=i["f1"], predictions_per_image=a["predictions_per_image"])


def main() -> int:
    rels = load_split("dev")
    gt = ground_truth(rels)
    by_name = {Path(r).name: r for r in rels}
    variants: dict[str, list[dict]] = {"sam3.1_open_text": [], "sam3.1_hosted_text": []}
    for rel in rels:
        s = Path(rel).stem
        variants["sam3.1_open_text"].append(image_stats(gt[rel], to_instances(json.loads(
            (DATA_DIR / "runs" / "sam_open" / "rust" / f"{s}.json").read_text(encoding="utf-8")), frame=0)))
        variants["sam3.1_hosted_text"].append(image_stats(gt[rel], parse_output(
            (HOSTED_DIR / "rust" / f"{s}.txt").read_text(encoding="utf-8"), 640, 640)))
    for tag in sys.argv[1:]:
        res = json.loads(fetch(tag).read_text(encoding="utf-8"))["results"]
        variants[f"sam3_{tag}"] = [image_stats(gt[by_name[name]], sam3_instances(recs)) for name, recs in res.items()]
    out = {k: summary(v) for k, v in variants.items()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for k, v in out.items():
        print(f"{k:22s} " + " ".join(f"{a} {b:.3f}" for a, b in v.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
