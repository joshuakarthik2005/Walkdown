import json

import cv2
import numpy as np
from PIL import Image

from benchmark.build_negatives import build


def _video(path, colours, fps=10, seconds_per_colour=2):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    rng = np.random.default_rng(0)
    for c in colours:
        base = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)  # distinct texture per segment
        base[:, :, 0] = c
        for _ in range(fps * seconds_per_colour):
            writer.write(base)
    writer.release()


def test_build_negatives_extracts_dedups_and_splits_by_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _video(src / "clip_a.mp4", [10, 200])     # 4 s -> 4 frames, 2 distinct
    _video(src / "clip_b.mp4", [90])          # 2 s -> 2 frames, 1 distinct
    rng = np.random.default_rng(1)
    for i in range(12):
        Image.fromarray(rng.integers(0, 255, (400, 1000, 3), dtype=np.uint8)).save(src / f"photo_{i:02d}.png")
    split_dir = tmp_path / "splits"
    m = build(src, out_dir=tmp_path / "frames", split_dir=split_dir, n_test_positives=40)

    assert m["source_files"] == 14 and m["frames_extracted"] == 4 + 2 + 12
    assert m["after_dedup"] == 2 + 1 + 12
    dev = (split_dir / "negatives_dev.txt").read_text().split()
    test = (split_dir / "negatives_test.txt").read_text().split()
    assert len(dev) >= 10 and not set(dev) & set(test)
    assert len(test) <= 10  # cap: 20% of (40 positives + negatives) -> 10
    for name in ("clip_a", "clip_b"):  # every frame of a source stays in one split
        assert not ({f for f in dev if name in f} and {f for f in test if name in f})
    assert max(Image.open(next((tmp_path / "frames").glob("photo_00*"))).size) == 640
    assert json.loads((split_dir / "negatives_manifest.json").read_text())["test_negatives"] == len(test)
