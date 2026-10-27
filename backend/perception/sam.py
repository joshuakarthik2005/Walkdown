"""SAM 3.1 segmentation over the Meta Model API (Responses API).

Request format follows https://dev.meta.ai/docs/sam/segmenting: one user
message with an ``input_text`` concept prompt (a short noun phrase) and an
``input_image`` (base64 data URL) or ``input_video`` (Files API ``file_id``).
Output is SAM's token text, parsed with Meta's ``meta-sam-parser``. Each mask
is a box-local raster the size of its box, pasted into a full-frame mask here.

Billing: $2.50 per 1,000 images; video $0.20 per 1,000 frames with a
50-frame minimum per request. Videos are re-encoded to a low frame rate
before upload so only the sampled frames are billed.
"""

from __future__ import annotations

import base64
import mimetypes
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import meta_sam_parser as msp
import numpy as np

from backend.clients.cost import CostEntry, CostLedger, sam_image_cost, sam_video_cost
from backend.clients.meta import meta_client, with_retries

MODEL = "sam-3.1"


@dataclass
class Instance:
    """One segmented object in one frame."""

    object_id: str
    box: tuple[int, int, int, int]  # left, top, right, bottom (half-open, source pixels)
    mask: np.ndarray  # bool, (height, width) of the full frame
    confidence: float | None
    frame: int = 0

    @property
    def area(self) -> int:
        """Mask area in pixels."""
        return int(self.mask.sum())


@dataclass
class SegmentationResult:
    """All instances for one prompt on one image or clip."""

    prompt: str
    width: int
    height: int
    instances: list[Instance]
    cost_usd: float
    raw_output: str = field(repr=False, default="")
    frames_billed: int = 0

    def frame(self, index: int) -> list[Instance]:
        """Instances on one frame (video)."""
        return [i for i in self.instances if i.frame == index]


def _frame_index(ref) -> int:
    if ref is None:
        return 0
    for name in ("index", "frame", "value", "number"):
        if hasattr(ref, name):
            return int(getattr(ref, name))
    return int(ref)


def parse_output(text: str, width: int, height: int, *, video: bool = False) -> list[Instance]:
    """Parse SAM output text into full-frame instances (one per mask record)."""
    fmt = msp.video_segmentation_format() if video else msp.image_segmentation_format()
    parser = fmt.create_parser()
    parser.push(text, emit=False)
    result = parser.finish(msp.CompletedOutcome()).result
    instances = []
    for rec in result.records:
        if not isinstance(rec, msp.SegmentationMaskRecord):
            continue
        b = rec.bounds
        left, top, right, bottom = int(b.left), int(b.top), int(b.right), int(b.bottom)
        local = np.frombuffer(msp.decode_mask_to_raster(rec.mask), dtype=np.uint8)
        local = local.reshape(rec.mask.height, rec.mask.width).astype(bool)
        if local.shape != (bottom - top, right - left):  # defensive: scale a downsampled raster to its box
            local = cv2.resize(local.astype(np.uint8), (right - left, bottom - top),
                               interpolation=cv2.INTER_NEAREST).astype(bool)
        full = np.zeros((height, width), dtype=bool)
        full[top:bottom, left:right] = local[: height - top, : width - left]
        instances.append(Instance(object_id=rec.object_id, box=(left, top, right, bottom), mask=full,
                                  confidence=rec.confidence, frame=_frame_index(rec.frame)))
    return instances


def _message(prompt: str, media: dict) -> list[dict]:
    return [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}, media]}]


def segment_image(
    image: Path | bytes,
    prompt: str,
    *,
    size: tuple[int, int] | None = None,
    ledger: CostLedger | None = None,
    job: str = "sam-image",
) -> SegmentationResult:
    """Segment every match of a concept prompt in one image.

    ``image`` is a path or JPEG/PNG bytes; ``size`` (width, height) is read from
    the image when omitted.
    """
    if isinstance(image, Path):
        data, mime = image.read_bytes(), mimetypes.guess_type(image.name)[0] or "image/jpeg"
    else:
        data, mime = image, "image/png" if image[:4] == b"\x89PNG" else "image/jpeg"
    if size is None:
        decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        size = (decoded.shape[1], decoded.shape[0])
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    resp = with_retries(lambda: meta_client().responses.create(
        model=MODEL, input=_message(prompt, {"type": "input_image", "image_url": url}),
        metadata={"include_confidence": "true"},
    ))
    images = getattr(resp.usage, "images_processed", None) or 1
    cost = sam_image_cost(images)
    if ledger is not None:
        ledger.add(CostEntry(job=job, model=MODEL, usd=cost, images=images))
    text = resp.output_text or ""
    return SegmentationResult(prompt=prompt, width=size[0], height=size[1],
                              instances=parse_output(text, *size), cost_usd=cost, raw_output=text)


def resample_video(src: Path, dst: Path, fps: float) -> tuple[int, int, int]:
    """Re-encode ``src`` at about ``fps`` as H.264 (accepted by SAM). Returns (frames, width, height)."""
    cap = cv2.VideoCapture(str(src))
    native = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(native / fps))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"avc1"), native / step, (w, h))
    if not out.isOpened():  # no H.264 encoder on this machine: fall back to MPEG-4 Part 2
        out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), native / step, (w, h))
    kept = index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step == 0:
            out.write(frame)
            kept += 1
        index += 1
    cap.release()
    out.release()
    return kept, w, h


def segment_video(
    video: Path,
    prompt: str,
    *,
    sample_fps: float = 2.0,
    ledger: CostLedger | None = None,
    job: str = "sam-video",
) -> SegmentationResult:
    """Segment and track a concept through a clip sampled at ``sample_fps``.

    UNVERIFIED: on a synthetic clip the request is accepted, billed and
    completes but returns no detections (the same frame as an image does).
    Re-check on real footage before relying on it.

    Frame indices in the result refer to the resampled clip: frame i is at
    about ``i / sample_fps`` seconds.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sampled = Path(tmp) / f"{video.stem}_{sample_fps:g}fps.mp4"
        frames, w, h = resample_video(video, sampled, sample_fps)
        with sampled.open("rb") as f:
            uploaded = with_retries(lambda: meta_client().files.create(file=f, purpose="user_data"))
    resp = with_retries(lambda: meta_client().responses.create(
        model=MODEL, input=_message(prompt, {"type": "input_video", "file_id": uploaded.id}),
        metadata={"include_confidence": "true"},
    ))
    cost = sam_video_cost(frames)
    if ledger is not None:
        ledger.add(CostEntry(job=job, model=MODEL, usd=cost, frames=max(frames, 50)))
    text = resp.output_text or ""
    return SegmentationResult(prompt=prompt, width=w, height=h, instances=parse_output(text, w, h, video=True),
                              cost_usd=cost, raw_output=text, frames_billed=max(frames, 50))
