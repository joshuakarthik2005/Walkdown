"""Training pool from the dataset's train split, with no near-duplicate of any evaluation image.

Used only for training (Glimmer verifier distillation, SAM 3.1 LoRA), never for evaluation.
The train split holds Roboflow augmentations (several copies per source image, possibly flipped
or rotated), so leakage into dev/test is checked conservatively:

1. Stock-style filenames are excluded (same rule as ``build_splits``).
2. Source filenames (before Roboflow's ``.rf.<hash>``) are generic and reused by unrelated images
   (e.g. ``L30_jpg`` appears 13 times in valid/test), so a name match alone is not proof of a copy.
   Measured null: for 159,797 unrelated train/test pairs, the minimum dHash distance over the 8
   flips/rotations is above 74 bits for 99.9% of pairs (median 112). A train image is dropped if it
   shares a source filename with a valid/test image and is within ``SAME_NAME_BITS`` (90, about the
   3rd percentile of the null) of any of them: an augmented copy (crop, brightness, noise) of an
   evaluation image.
3. A train image is dropped if any of its 8 flips/rotations is within ``ANY_BITS`` (40; 0.02% of
   unrelated pairs) of any valid/test image, whatever its name. Valid and test are used in full,
   not only the sampled dev/test splits, so every cluster touching dev or test is excluded.
4. At most ``PER_SOURCE`` augmented copies per source filename are kept, so heavily augmented
   sources do not dominate the pool.

Writes benchmark/splits/train_pool.txt and train_pool_manifest.json.

    .venv\\Scripts\\python.exe -m benchmark.train_pool
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from benchmark.build_splits import STOCK_PATTERN, original_stem
from benchmark.download_dataset import RAW_DIR
from benchmark.splits import SPLIT_DIR, load_split

SAME_NAME_BITS = 90
ANY_BITS = 40
PER_SOURCE = 3
POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def dhash_variants(path: Path) -> np.ndarray:
    """Packed 256-bit dHashes of the image under the 8 flips/rotations, shape (8, 32)."""
    img = Image.open(path).convert("L")
    out = []
    for k in range(4):
        rot = img.rotate(90 * k, expand=True)
        for im in (rot, rot.transpose(Image.FLIP_LEFT_RIGHT)):
            g = np.asarray(im.resize((17, 16), Image.BILINEAR), dtype=float)
            out.append(np.packbits(g[:, 1:] > g[:, :-1]))
    return np.stack(out)


def min_distance(queries: np.ndarray, refs: np.ndarray, chunk: int = 256) -> np.ndarray:
    """For packed hashes queries (n, 32) and refs (m, 32): min Hamming distance per query."""
    best = np.empty(len(queries), dtype=np.int32)
    for i in range(0, len(queries), chunk):
        x = queries[i:i + chunk, None, :] ^ refs[None, :, :]
        best[i:i + chunk] = POPCOUNT[x].sum(-1, dtype=np.int32).min(1)
    return best


def coco_records(split: str) -> list[tuple[str, int]]:
    coco = json.loads((RAW_DIR / split / "_annotations.coco.json").read_text(encoding="utf-8"))
    per_image = defaultdict(int)
    for a in coco["annotations"]:
        per_image[a["image_id"]] += 1
    return [(f"{split}/{img['file_name']}", per_image[img["id"]]) for img in coco["images"]]


def main() -> int:
    evals = coco_records("valid") + coco_records("test")
    eval_hashes = np.stack([dhash_variants(RAW_DIR / p)[0] for p, _ in evals])
    train = coco_records("train")
    stock = [r for r in train if STOCK_PATTERN.search(original_stem(Path(r[0]).name))]
    candidates = [r for r in train if r not in stock]
    eval_by_stem: dict[str, list[int]] = defaultdict(list)
    for j, (p, _) in enumerate(evals):
        eval_by_stem[original_stem(Path(p).name).lower()].append(j)

    variants = np.stack([dhash_variants(RAW_DIR / p) for p, _ in candidates])  # (n, 8, 32)
    dist_any = min_distance(variants.reshape(-1, 32), eval_hashes).reshape(len(candidates), 8).min(1)
    same_source, near_eval, keep_idx = [], [], []
    for i, (p, _) in enumerate(candidates):
        same = eval_by_stem.get(original_stem(Path(p).name).lower())
        if same and min_distance(variants[i], eval_hashes[same]).min() <= SAME_NAME_BITS:
            same_source.append(candidates[i])
        elif dist_any[i] <= ANY_BITS:
            near_eval.append(candidates[i])
        else:
            keep_idx.append(i)

    by_source: dict[str, list[int]] = defaultdict(list)
    for i in sorted(keep_idx, key=lambda i: candidates[i][0]):
        group = by_source[original_stem(Path(candidates[i][0]).name).lower()]
        if len(group) < PER_SOURCE:
            group.append(i)
    pool = sorted(candidates[i] for group in by_source.values() for i in group)

    SPLIT_DIR.mkdir(exist_ok=True)
    (SPLIT_DIR / "train_pool.txt").write_text("".join(p + "\n" for p, _ in pool), encoding="utf-8")
    dev, test = set(load_split("dev")), set(load_split("test"))
    assert not ({p for p, _ in pool} & (dev | test))
    manifest = dict(
        purpose="training only (verifier distillation, SAM LoRA); never evaluation",
        train_images=len(train), excluded_stock_style_names=len(stock),
        excluded_same_name_and_within_90_bits=len(same_source),
        excluded_within_40_bits_of_any_valid_or_test=len(near_eval),
        null_distance_unrelated_pairs="99.9% above 74 bits, median 112 (159,797 pairs)",
        hash_variants="8 flips/rotations of each train image vs every valid/test image",
        after_exclusion=len(keep_idx), unique_sources=len(by_source), max_copies_per_source=PER_SOURCE, pool=len(pool),
        pool_positives=sum(n > 0 for _, n in pool), pool_negatives=sum(n == 0 for _, n in pool),
    )
    (SPLIT_DIR / "train_pool_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
