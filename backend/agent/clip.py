"""Walkdown clips: a video file or a folder of photos, stored on WALKDOWN_DATA_DIR.

Frames are sampled on demand and saved as JPG so every SAM call and every
verdict can be cached per (clip, frame). A folder of photos is treated as a
clip with one frame per photo at 1-second spacing.
"""

from __future__ import annotations

import json
import shutil
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv

from backend.agent.register import AssetInfo
from backend.clients.meta import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env", override=True)
CLIPS_DIR = Path(os.environ.get("WALKDOWN_DATA_DIR", "G:/walkdown-data")) / "clips"
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv"}
PHOTO_EXT = {".jpg", ".jpeg", ".png"}


@dataclass
class Frame:
    """One sampled frame."""

    index: int
    time_s: float
    path: Path

    def image(self) -> np.ndarray:
        return cv2.imread(str(self.path), cv2.IMREAD_COLOR)


class Clip:
    """A stored walkdown clip with asset metadata."""

    def __init__(self, clip_id: str) -> None:
        self.clip_id = clip_id
        self.dir = CLIPS_DIR / clip_id
        if not self.dir.exists():
            raise FileNotFoundError(f"clip {clip_id!r} not found")
        meta_path = self.dir / "clip.json"
        self.meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self.asset = AssetInfo(**self.meta.get("asset", {"asset_id": clip_id}))
        self.source = next((p for p in self.dir.iterdir() if p.suffix.lower() in VIDEO_EXT), None)
        self.photos = sorted(p for p in (self.dir / "photos").glob("*") if p.suffix.lower() in PHOTO_EXT) \
            if (self.dir / "photos").exists() else []
        # A bundled demo clip ships its extracted frames and caches but not the source video (stock footage is
        # not redistributed): clip.json "video" = {"duration_s": ...} stands in for the file.
        self.bundled = self.source is None and "video" in self.meta

    @property
    def is_video(self) -> bool:
        return self.source is not None or self.bundled

    @property
    def duration_s(self) -> float:
        if self.bundled:
            return float(self.meta["video"]["duration_s"])
        if self.source is None:
            return float(len(self.photos))
        cap = cv2.VideoCapture(str(self.source))
        frames, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.release()
        return frames / fps

    def frames(self, start_s: float = 0.0, end_s: float | None = None, fps: float = 1.0) -> list[Frame]:
        """Frames in ``[start_s, end_s]`` at about ``fps``; extracted once and cached as JPG."""
        end_s = self.duration_s if end_s is None else min(end_s, self.duration_s)
        if self.source is None and not self.bundled:
            return [Frame(i, float(i), p) for i, p in enumerate(self.photos) if start_s <= i <= end_s]
        out_dir = self.dir / "frames"
        if self.bundled:  # frames were extracted before bundling; same 0.1 s grid ids
            return [Frame(int(round(t * 10)), float(t), out_dir / f"t{int(round(t * 10)):05d}.jpg")
                    for t in np.arange(start_s, end_s + 1e-9, 1.0 / fps)]
        out_dir.mkdir(exist_ok=True)
        cap = cv2.VideoCapture(str(self.source))
        native = cap.get(cv2.CAP_PROP_FPS) or 30.0
        wanted = np.arange(start_s, end_s + 1e-9, 1.0 / fps)
        frames = []
        for t in wanted:
            index = int(round(t * 10))  # frame ids on a 0.1 s grid, stable across sampling rates
            path = out_dir / f"t{index:05d}.jpg"
            if not path.exists():
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * native)))
                ok, img = cap.read()
                if not ok:
                    continue
                cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            frames.append(Frame(index, float(t), path))
        cap.release()
        return frames


def create_clip(clip_id: str, *, video: Path | None = None, photos: list[Path] | None = None,
                asset: dict | None = None) -> Clip:
    """Store a new clip from a video file or a list of photos."""
    d = CLIPS_DIR / clip_id
    d.mkdir(parents=True, exist_ok=True)
    if video is not None:
        shutil.copyfile(video, d / f"source{video.suffix.lower()}")  # streamed: uploads can be large
    for i, p in enumerate(photos or []):
        (d / "photos").mkdir(exist_ok=True)
        shutil.copyfile(p, d / "photos" / f"{i:04d}{p.suffix.lower()}")
    (d / "clip.json").write_text(json.dumps({"asset": asset or {"asset_id": clip_id}}, indent=1), encoding="utf-8")
    return Clip(clip_id)
