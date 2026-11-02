"""Curated sample walkdowns (stock demonstration footage) and their finished example runs.

Clips are Pexels stock videos (Pexels License: free to use inside a larger work, no standalone redistribution).
Only extracted, downscaled frames and Walkdown's cached results are used; the source videos are never served.
Authors and links: docs/FOOTAGE_SOURCES.md.
"""

from __future__ import annotations

from pathlib import Path

import cv2

from backend.agent.clip import CLIPS_DIR, Clip

SAMPLES: dict[str, dict] = {
    "stock-tank-farm": dict(
        title="Tank farm pipe rack",
        description="A walk past storage tanks and a pipe rack with rust on supports, flanges and pipe runs.",
        credit=dict(author="Mumtaz Niazi", source="Pexels", licence="Pexels License",
                    url="https://www.pexels.com/video/industrial-power-plant-pipes-and-chimneys-35596447/"),
        example="tank-farm"),
    "stock-valve-tank": dict(
        title="Valve at a tank bottom",
        description="Close-up of an old fuel transfer valve and the tank shell around it.",
        credit=dict(author="Matthias Groeneveld", source="Pexels", licence="Pexels License",
                    url="https://www.pexels.com/video/close-up-of-an-old-fuel-transfer-valve-11662354/"),
        example="valve-tank"),
    "stock-clean-piping": dict(
        title="Clean painted piping",
        description="A false-alarm check: well-kept painted plant piping with no corrosion.",
        credit=dict(author="Salim Da", source="Pexels", licence="Pexels License",
                    url="https://www.pexels.com/video/industrial-pipelines-and-valves-system-30243437/"),
        example="clean-piping"),
}

EXAMPLES: dict[str, dict] = {
    "tank-farm": dict(sample="stock-tank-farm", title="Tank farm: full run, crew-out replan and a voice note",
                      includes=["agent run", "voice note", "replan: coating crew out for 72 h"]),
    "valve-tank": dict(sample="stock-valve-tank", title="Valve at a tank bottom: full run",
                       includes=["agent run"]),
    "clean-piping": dict(sample="stock-clean-piping", title="Clean piping: no false alarm",
                         includes=["agent run"]),
}


def is_sample(clip_id: str) -> bool:
    return clip_id in SAMPLES


def sample_info(clip_id: str) -> dict | None:
    """Catalogue entry plus the clip's asset metadata, or None if the clip is not on this server."""
    try:
        clip = Clip(clip_id)
    except FileNotFoundError:
        return None
    return dict(id=clip_id, **SAMPLES[clip_id], asset=clip.asset.__dict__, duration_s=round(clip.duration_s, 1),
                thumbnail=f"/samples/{clip_id}/thumbnail.jpg")


def thumbnail(clip_id: str, width: int = 480) -> bytes:
    """A downscaled middle frame of the sample (cached next to the clip)."""
    out = CLIPS_DIR / clip_id / "thumbnail.jpg"
    if out.exists():
        return out.read_bytes()
    frames = sorted((CLIPS_DIR / clip_id / "frames").glob("t*.jpg"))
    if not frames:
        raise FileNotFoundError(clip_id)
    img = cv2.imread(str(frames[len(frames) // 2]), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    out.write_bytes(buf.tobytes())
    return buf.tobytes()


def sample_dir(clip_id: str) -> Path:
    return CLIPS_DIR / clip_id
