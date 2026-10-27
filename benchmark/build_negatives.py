"""Build the negatives set from the builder's own clips and photos.

Negatives are images with no corrosion: clean or look-alike surfaces (painted
pipes, stainless, galvanised steel, water stains, shadows, orange/red paint).
They measure the verifier's main job, rejecting false positives.

- Videos (.mp4/.mov/.avi/.mkv): frames sampled at ~1 fps.
- Photos (.jpg/.jpeg/.png): used as-is. Convert HEIC to JPG first.
All images are resized so the longer side is 640 px (the dataset's size) and
written as JPG to ``<WALKDOWN_DATA_DIR>/negatives/frames``. Near-duplicates are
removed with the same 16x16 dHash clustering (<= 10 bits) as the positive splits.

To avoid leakage, every frame from one source file goes to the same split:
whole sources are assigned to dev until it has ``DEV_NEGATIVES`` frames, the
rest go to test, capped so negatives are about ``TARGET_SHARE`` of the test split.

    .venv\\Scripts\\python.exe -m benchmark.build_negatives <folder with clips and photos>
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .build_splits import HASH_THRESHOLD, cluster, dhash
from .download_dataset import DATA_DIR
from .splits import SEED, SPLIT_DIR, load_split

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv"}
PHOTO_EXT = {".jpg", ".jpeg", ".png"}
OUT_DIR = DATA_DIR / "negatives" / "frames"
DEV_NEGATIVES = 10
TARGET_SHARE = 0.20
MAX_SIDE = 640


def _resize(img: Image.Image) -> Image.Image:
    scale = MAX_SIDE / max(img.size)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR) if scale < 1 else img


def extract_video(path: Path, out_dir: Path, fps: float = 1.0) -> list[Path]:
    """Save about ``fps`` frames per second of video as JPG; returns the written paths."""
    cap = cv2.VideoCapture(str(path))
    native = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(native / fps))
    written, index = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step == 0:
            img = _resize(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
            target = out_dir / f"{path.stem}_t{index / native:07.1f}s.jpg"
            img.save(target, quality=92)
            written.append(target)
        index += 1
    cap.release()
    return written


def extract_photo(path: Path, out_dir: Path) -> list[Path]:
    """Resize and save a photo as JPG."""
    target = out_dir / f"{path.stem}.jpg"
    _resize(Image.open(path).convert("RGB")).save(target, quality=92)
    return [target]


def build(source_dir: Path, out_dir: Path = OUT_DIR, split_dir: Path = SPLIT_DIR,
          n_test_positives: int | None = None) -> dict:
    """Extract, dedup and split negatives; write file lists and a manifest. Returns the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[Path, str]] = []  # (frame path, source file name)
    sources = sorted(p for p in source_dir.iterdir() if p.suffix.lower() in VIDEO_EXT | PHOTO_EXT)
    for src in sources:
        made = extract_video(src, out_dir) if src.suffix.lower() in VIDEO_EXT else extract_photo(src, out_dir)
        frames += [(f, src.name) for f in made]
    if not frames:
        raise SystemExit(f"no videos or photos found in {source_dir}")

    clusters = cluster(np.stack([dhash(f) for f, _ in frames]), HASH_THRESHOLD)
    keep: dict[int, tuple[Path, str]] = {}
    for item, cid in sorted(zip(frames, clusters), key=lambda x: str(x[0][0])):
        keep.setdefault(cid, item)
    unique = sorted(keep.values(), key=lambda x: str(x[0]))

    by_source: dict[str, list[str]] = {}
    for f, src in unique:
        by_source.setdefault(src, []).append(f"negatives/frames/{f.name}")
    order = sorted(by_source)
    random.Random(SEED).shuffle(order)
    dev, test = [], []
    for src in order:
        (dev if len(dev) < DEV_NEGATIVES else test).extend(by_source[src])

    if n_test_positives is None:
        n_test_positives = len(load_split("test", split_dir))
    cap = round(n_test_positives * TARGET_SHARE / (1 - TARGET_SHARE))
    dropped = max(0, len(test) - cap)
    test = sorted(random.Random(SEED).sample(test, min(cap, len(test))))

    split_dir.mkdir(parents=True, exist_ok=True)
    (split_dir / "negatives_dev.txt").write_text("\n".join(sorted(dev)) + "\n", encoding="utf-8")
    (split_dir / "negatives_test.txt").write_text("\n".join(test) + "\n", encoding="utf-8")
    manifest = {
        "source": "Recorded by the builder (Joshua Karthik Ashok) during the hackathon; CC BY 4.0",
        "source_files": len(sources),
        "frames_extracted": len(frames),
        "after_dedup": len(unique),
        "hash_threshold_bits": HASH_THRESHOLD,
        "dev_negatives": len(dev),
        "test_negatives": len(test),
        "test_negatives_dropped_by_cap": dropped,
        "test_positives": n_test_positives,
        "test_negative_share": len(test) / (len(test) + n_test_positives),
        "sources": {src: len(v) for src, v in sorted(by_source.items())},
    }
    (split_dir / "negatives_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    print(json.dumps(build(Path(sys.argv[1])), indent=1))
