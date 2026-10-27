"""Build the fixed dev and test splits from the Roboflow corrosion dataset.

Only the dataset's own valid and test folders are used (train holds
Roboflow-augmented copies). Before splitting:

1. Near-duplicates are grouped: images whose 16x16 difference hash differs in
   at most ``HASH_THRESHOLD`` bits form one cluster, and only one image per
   cluster is kept. Dev and test therefore share no near-duplicate.
2. Images whose original filename looks like a commercial stock photo
   (Adobe Stock, iStock, Shutterstock, Alamy-style ids, ...) are excluded:
   the Roboflow "Public Domain" label is the uploader's claim, and these
   images may still be copyrighted. They are not sent to any API.

Writes benchmark/splits/{dev,test}.txt (paths relative to the dataset root)
and benchmark/splits/manifest.json with all counts.

    .venv\\Scripts\\python.exe -m benchmark.build_splits
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from .download_dataset import RAW_DIR
from .splits import SEED, SPLIT_DIR, make_splits, save_splits

HASH_THRESHOLD = 10
DEV_SIZE = 50
TEST_SIZE = 1500
STOCK_PATTERN = re.compile(
    r"(^\d+_F_\d+_)|istock|shutterstock|alamy|adobe|depositphotos|dreamstime|123rf|getty|"
    r"stock-photo|-[0-9A-Z]{7}_jpg$",
    re.IGNORECASE,
)


def original_stem(file_name: str) -> str:
    """Strip Roboflow's '.rf.<hash>.jpg' suffix to recover the uploaded filename."""
    return file_name.split(".rf.")[0]


def dhash(path: Path) -> np.ndarray:
    """256-bit difference hash."""
    g = np.asarray(Image.open(path).convert("L").resize((17, 16), Image.BILINEAR), dtype=float)
    return (g[:, 1:] > g[:, :-1]).flatten()


def cluster(hashes: np.ndarray, threshold: int) -> list[int]:
    """Union-find over pairs within ``threshold`` Hamming distance; returns a cluster id per item."""
    parent = list(range(len(hashes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    dist = (hashes[:, None, :] != hashes[None, :, :]).sum(-1)
    for i, j in zip(*np.where(np.triu(dist <= threshold, 1))):
        parent[find(i)] = find(j)
    return [find(i) for i in range(len(hashes))]


def main() -> int:
    records = []  # (relative path, n_instances)
    for split in ("valid", "test"):
        coco = json.loads((RAW_DIR / split / "_annotations.coco.json").read_text(encoding="utf-8"))
        per_image = defaultdict(int)
        for a in coco["annotations"]:
            per_image[a["image_id"]] += 1
        records += [(f"{split}/{img['file_name']}", per_image[img["id"]]) for img in coco["images"]]

    stock = [r for r in records if STOCK_PATTERN.search(original_stem(Path(r[0]).name))]
    kept = [r for r in records if r not in stock]
    hashes = np.stack([dhash(RAW_DIR / r[0]) for r in kept])
    clusters = cluster(hashes, HASH_THRESHOLD)
    representative: dict[int, tuple[str, int]] = {}
    for rec, cid in sorted(zip(kept, clusters)):
        representative.setdefault(cid, rec)
    unique = sorted(representative.values())

    positives = [p for p, n in unique if n > 0]
    negatives = [p for p, n in unique if n == 0]
    test_size = min(TEST_SIZE, len(unique) - DEV_SIZE)
    splits = make_splits(positives, negatives, dev_size=DEV_SIZE, test_size=test_size)
    save_splits(splits)

    instances = dict(unique)
    manifest = {
        "dataset": "Roboflow Universe computervision-adpf6/corrosion-segmentation-xybsj v1 (coco-segmentation)",
        "source_url": "https://universe.roboflow.com/computervision-adpf6/corrosion-segmentation-xybsj",
        "licence_listed": "Public Domain",
        "seed": SEED,
        "hash_threshold_bits": HASH_THRESHOLD,
        "images_in_valid_and_test": len(records),
        "excluded_stock_style_names": len(stock),
        "after_exclusion": len(kept),
        "near_duplicate_clusters": len(unique),
        "zero_annotation_images_available": len(negatives),
        "dev": {"images": len(splits.dev), "negatives": splits.dev_negatives,
                "instances": sum(instances[p] for p in splits.dev)},
        "test": {"images": len(splits.test), "negatives": splits.test_negatives,
                 "instances": sum(instances[p] for p in splits.test)},
    }
    (SPLIT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
