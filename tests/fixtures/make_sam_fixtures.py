"""Regenerate SAM output fixtures from synthetic media (costs about $0.0125).

The media are drawn here (no third-party content): a grey steel plate with
two rust-coloured, textured patches. Raw SAM output is saved so parser tests
run offline.

    .venv\\Scripts\\python.exe -m tests.fixtures.make_sam_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from backend.clients.cost import CostLedger
from backend.perception.sam import segment_image, segment_video

HERE = Path(__file__).parent
# Synthetic "rust" is not recognised as rust by SAM (empty output), so fixtures use a shape concept.
PROMPT = "circle"


def synthetic_plate(shift: int = 0, seed: int = 0) -> np.ndarray:
    """640x480 BGR steel plate with two rust patches; ``shift`` moves them right."""
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 150, np.uint8) + rng.integers(-12, 12, (480, 640, 3)).astype(np.uint8)
    for cx, cy, r in ((200 + shift, 200, 70), (430 + shift, 320, 50)):
        yy, xx = np.ogrid[:480, :640]
        blob = (xx - cx) ** 2 + (yy - cy) ** 2 < (r + rng.normal(0, 6, (480, 640))) ** 2
        rust = np.stack([20 + rng.integers(0, 30, blob.sum()), 60 + rng.integers(0, 40, blob.sum()),
                         120 + rng.integers(0, 60, blob.sum())], axis=1).astype(np.uint8)
        img[blob] = rust
    return img


def main() -> None:
    ledger = CostLedger()
    ok, png = cv2.imencode(".png", synthetic_plate())
    img = segment_image(png.tobytes(), PROMPT, ledger=ledger)
    (HERE / "sam_image.txt").write_text(img.raw_output, encoding="utf-8")

    video = HERE / "_synthetic_plate.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 480))
    for t in range(30):
        writer.write(synthetic_plate(shift=2 * t, seed=t))
    writer.release()
    vid = segment_video(video, PROMPT, sample_fps=2.0, ledger=ledger)
    video.unlink()
    (HERE / "sam_video.txt").write_text(vid.raw_output, encoding="utf-8")

    meta = {"image": {"instances": len(img.instances), "size": [img.width, img.height]},
            "video": {"instances": len(vid.instances), "frames": sorted({i.frame for i in vid.instances}),
                      "size": [vid.width, vid.height], "frames_billed": vid.frames_billed},
            "cost": ledger.summary()}
    (HERE / "sam_fixtures.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
