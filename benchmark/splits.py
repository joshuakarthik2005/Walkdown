"""Fixed, seeded dev and test splits saved as plain file lists.

- dev: about 50 images for dry runs and prompt tuning.
- test: 1,000-2,000 held-out images, never used for tuning.
Both are stratified by positive (has a corrosion instance) vs negative (no
instance), so the negative share is the same in each. The two are disjoint,
and the lists are sorted so diffs of the files stay readable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

SPLIT_DIR = Path(__file__).parent / "splits"
SEED = 20261027


@dataclass(frozen=True)
class Splits:
    """Image ids in each split, with the positive/negative breakdown."""

    dev: list[str]
    test: list[str]
    dev_negatives: int
    test_negatives: int


def make_splits(
    positives: list[str],
    negatives: list[str],
    *,
    dev_size: int = 50,
    test_size: int = 1500,
    seed: int = SEED,
) -> Splits:
    """Sample disjoint, stratified dev and test splits from the available images."""
    pos, neg = sorted(set(positives)), sorted(set(negatives))
    if set(pos) & set(neg):
        raise ValueError("an image cannot be both positive and negative")
    total = len(pos) + len(neg)
    if dev_size + test_size > total:
        raise ValueError(f"need {dev_size + test_size} images, only {total} available")
    rng = random.Random(seed)
    rng.shuffle(pos)
    rng.shuffle(neg)
    neg_share = len(neg) / total

    def take(size: int, offset_pos: int, offset_neg: int) -> tuple[list[str], int, int]:
        n_neg = min(round(size * neg_share), len(neg) - offset_neg)
        n_pos = size - n_neg
        return pos[offset_pos:offset_pos + n_pos] + neg[offset_neg:offset_neg + n_neg], n_pos, n_neg

    dev, dp, dn = take(dev_size, 0, 0)
    test, _, tn = take(test_size, dp, dn)
    return Splits(dev=sorted(dev), test=sorted(test), dev_negatives=dn, test_negatives=tn)


def save_splits(splits: Splits, directory: Path = SPLIT_DIR) -> None:
    """Write dev.txt and test.txt, one image id per line."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dev.txt").write_text("\n".join(splits.dev) + "\n", encoding="utf-8")
    (directory / "test.txt").write_text("\n".join(splits.test) + "\n", encoding="utf-8")


def load_split(name: str, directory: Path = SPLIT_DIR) -> list[str]:
    """Read a saved split ('dev' or 'test')."""
    return [line for line in (directory / f"{name}.txt").read_text(encoding="utf-8").splitlines() if line]
