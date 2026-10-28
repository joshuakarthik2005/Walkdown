"""Stock demonstration clips (Pexels; docs/FOOTAGE_SOURCES.md) through the full agent pipeline, Cloud mode.

Each clip is downscaled to 1,280 px on its long side and cut to at most 20 s (smaller uploads and masks), stored
as a Walkdown clip on G: (never committed), and run twice with the agent (fill + repeat, as warm_cache): the
repeat run shows what the cached demo path costs. Reports register size, walkdown jobs, plan status, cost, time.

    .venv\\Scripts\\python.exe -m benchmark.stock_clips
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

from backend.agent.clip import CLIPS_DIR, create_clip
from backend.agent.warm_cache import run_once
from benchmark.download_dataset import DATA_DIR

STOCK = DATA_DIR / "footage_stock"
RESULTS = Path(__file__).parent / "results"
MAX_SIDE, MAX_S = 1280, 20.0
CLIPS = {  # clip id -> (file, asset metadata)
    "stock-valve-tank": ("pexels_11662354.mp4", dict(asset_id="STOCK-TANK-VALVE", asset_type="tank", pressurised=False,
                                                     service="crude", location="fuel transfer valve, tank bottom")),
    "stock-welded-pipes": ("pexels_5571839.mp4", dict(asset_id="STOCK-PIPE-WELDS", asset_type="pipe", pressurised=True,
                                                      service="cooling_water", location="welded pipe joints")),
    "stock-vessel": ("pexels_35069362.mp4", dict(asset_id="STOCK-VESSEL", asset_type="tank", pressurised=True,
                                                 service="hydrocarbon_vapour", location="horizontal vessel shell")),
    "stock-tank-farm": ("pexels_35596447.mp4", dict(asset_id="STOCK-TANK-FARM", asset_type="pipe", pressurised=True,
                                                    service="crude", location="tank farm pipe rack")),
    "stock-rusty-pipe": ("pexels_34633267.mp4", dict(asset_id="STOCK-RUSTY-PIPE", asset_type="pipe", pressurised=False,
                                                     service="fire_water", location="old outdoor pipe")),
    "stock-clean-piping": ("pexels_30243437.mp4", dict(asset_id="STOCK-CLEAN-PIPING", asset_type="pipe",
                                                       pressurised=True, service="steam", location="painted plant piping")),
}


def downscale(src: Path, dst: Path) -> dict:
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s = min(1.0, MAX_SIDE / max(w, h))
    size = (int(w * s) // 2 * 2, int(h * s) // 2 * 2)
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"avc1"), fps, size)
    if not out.isOpened():
        out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    n = 0
    while n < fps * MAX_S:
        ok, frame = cap.read()
        if not ok:
            break
        out.write(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
        n += 1
    cap.release()
    out.release()
    return dict(size=size, seconds=round(n / fps, 1))


def main() -> int:
    only = sys.argv[1:]
    results = {}
    out_file = RESULTS / "stock_clips.json"
    if out_file.exists():
        results = json.loads(out_file.read_text(encoding="utf-8"))
    for clip_id, (fname, asset) in CLIPS.items():
        if only and clip_id not in only:
            continue
        if not (CLIPS_DIR / clip_id).exists():
            tmp = STOCK / f"small_{fname}"
            info = downscale(STOCK / fname, tmp)
            create_clip(clip_id, video=tmp, asset=asset)
        else:
            info = results.get(clip_id, {}).get("video", {})
        runs = {label: run_once(clip_id, "minimal") for label in ("fill", "repeat")}
        results[clip_id] = dict(file=fname, video=info, **runs)
        print(clip_id, json.dumps(results[clip_id]), flush=True)
        RESULTS.mkdir(exist_ok=True)
        out_file.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
