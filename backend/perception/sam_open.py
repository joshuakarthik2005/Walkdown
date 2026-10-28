"""SAM 3.1 open weights on Modal: the perception backend of Walkdown's On-prem mode.

Calls the deployed Modal app ``walkdown-sam31`` (``modal_apps/sam_open.py``): the official SAM 3.1 Object
Multiplex predictor on one L40S GPU, scaling to zero when idle. Results come back as COCO RLE and are turned into
the same ``Instance`` objects as the hosted SAM 3.1 client, so the rest of the pipeline does not change.

Cost is recorded from wall time at the L40S list rate (an estimate; the Modal billing report is the reference).
A cold start (container boot and model load) is included in the first call's wall time.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from backend.clients.cost import CostEntry, CostLedger
from backend.perception.sam import Instance

APP = "walkdown-sam31"
CLS = "Sam31"
L40S_PER_SECOND = 1.95 / 3600  # USD, Modal list price checked 2026-10-28
MODEL = "sam3.1-open (Modal L40S)"


def _sam31():
    import modal
    return modal.Cls.from_name(APP, CLS)()


def to_instances(records: list[dict], frame: int | None = None) -> list[Instance]:
    """Instances from the Modal app's RLE records (``frame`` overrides the record's frame index)."""
    from pycocotools import mask as mask_utils
    out = []
    for r in records:
        rle = dict(r["rle"])
        rle["counts"] = rle["counts"].encode()
        mask = mask_utils.decode(rle).astype(bool)
        if not mask.any():
            continue
        ys, xs = np.nonzero(mask)
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        out.append(Instance(object_id=str(r["obj_id"]), box=box, mask=mask, confidence=float(r["score"]),
                            frame=r["frame"] if frame is None else frame))
    return out


def _record(ledger: CostLedger | None, job: str, seconds: float, images: int = 0, frames: int = 0) -> None:
    if ledger is not None:
        ledger.add(CostEntry(job=job, model=MODEL, usd=seconds * L40S_PER_SECOND, images=images, frames=frames))


def segment_images_open(paths: list[Path], prompt: str, *, ledger: CostLedger | None = None,
                        job: str = "sam-open") -> list[list[dict]]:
    """Raw RLE records per image (one independent session per image)."""
    t0 = time.perf_counter()
    records = _sam31().segment_images.remote([p.read_bytes() for p in paths], prompt)
    _record(ledger, job, time.perf_counter() - t0, images=len(paths))
    return records


def segment_video_open(paths: list[Path], prompt: str, *, ledger: CostLedger | None = None,
                       job: str = "sam-open-video") -> list[dict]:
    """Raw RLE records for a frame sequence: text prompt on frame 0, tracked through all frames."""
    t0 = time.perf_counter()
    records = _sam31().segment.remote([p.read_bytes() for p in paths], prompt, True)
    _record(ledger, job, time.perf_counter() - t0, frames=len(paths))
    return records
