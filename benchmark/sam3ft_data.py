"""COCO export for the SAM 3 full fine-tune (Modal): train pool + FLUX-train negatives; dev for evaluation.

Layout expected by the sam3 Roboflow fine-tune config (``<root>/<name>/{train,test}/_annotations.coco.json``):
- train/: the 585 clean train-pool images with their corrosion polygons (near-duplicate clusters disjoint from dev
  and test; benchmark/train_pool.py), plus the FLUX-train look-alike images as negatives (no annotations; FLUX
  "train" subset only, the categories that render without rust). Training data only.
- test/: the 50 dev images with their annotations (validation during training and our own evaluation).
One category, named "rust" (the production text prompt), id 1. The dataset's own class names are not prompts.

    .venv\\Scripts\\python.exe -m benchmark.sam3ft_data
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from PIL import Image

from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.glimmer_data import AMBIGUOUS_LOOKALIKES, FLUX_DIR
from benchmark.splits import load_split

OUT = DATA_DIR / "sam3ft" / "rust"
CATEGORY = {"id": 1, "name": "rust", "supercategory": "defect"}


def _coco(split: str) -> tuple[dict, dict]:
    d = json.loads((RAW_DIR / split / "_annotations.coco.json").read_text(encoding="utf-8"))
    by_img: dict[int, list] = {}
    for a in d["annotations"]:
        by_img.setdefault(a["image_id"], []).append(a)
    return {i["file_name"]: i for i in d["images"]}, by_img


def export(folder: str, rels: list[str], negatives: list[Path]) -> dict:
    out = OUT / folder
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    images, anns = [], []
    cache: dict[str, tuple[dict, dict]] = {}
    for rel in rels:
        split, name = rel.split("/", 1)
        if split not in cache:
            cache[split] = _coco(split)
        imgs, by_img = cache[split]
        im = imgs[name]
        new_id = len(images) + 1
        shutil.copy2(RAW_DIR / rel, out / name)
        images.append(dict(id=new_id, file_name=name, width=im["width"], height=im["height"]))
        for a in by_img.get(im["id"], []):
            if not a.get("segmentation"):
                continue
            anns.append(dict(id=len(anns) + 1, image_id=new_id, category_id=1, bbox=a["bbox"], area=a["area"],
                             segmentation=a["segmentation"], iscrowd=0))
    for p in negatives:
        new_id = len(images) + 1
        name = f"neg_{p.name}"
        shutil.copy2(p, out / name)
        w, h = Image.open(p).size
        images.append(dict(id=new_id, file_name=name, width=w, height=h))
    coco = dict(images=images, annotations=anns, categories=[CATEGORY])
    (out / "_annotations.coco.json").write_text(json.dumps(coco), encoding="utf-8")
    return dict(images=len(images), positives=len(rels), negatives=len(negatives), annotations=len(anns))


def main() -> int:
    man = [json.loads(l) for l in (FLUX_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    flux_train = [FLUX_DIR / m["file"] for m in man
                  if m.get("subset") == "train" and m["lookalike"] not in AMBIGUOUS_LOOKALIKES]
    res = dict(train=export("train", load_split("train_pool"), flux_train), test=export("test", load_split("dev"), []))
    (OUT.parent / "export_summary.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
