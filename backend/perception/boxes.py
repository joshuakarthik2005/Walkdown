"""Box proposals: Muse Spark lists rust boxes on a frame, SAM 3.1 segments inside them.

The default perception pipeline is text + boxes + verifier (benchmark/RESULTS.md section 4): SAM 3.1 with the
text prompt "rust", plus these box-prompted masks, merged by overlap. On the test split this raised image
detection from 66% to 98% and gave the best instance F1 once candidates are verified.

1. ``propose_boxes``: ``muse-spark-1.3``, reasoning effort minimal, strict JSON schema; up to 16 boxes in
   pixel coordinates of the frame.
2. ``box_masks``: SAM 3.1 object prompts, one per box (box prompts and a text concept cannot be mixed in one
   request, so this is a second SAM call).
3. ``merge_with_text``: overlap merge of text and box masks. A merged instance that is essentially a text
   instance (mask IoU >= 0.9) keeps that text instance's id, so its verdict is reused.

On-prem mode uses open weights for both steps: ``propose_boxes(..., provider="baseten")`` asks Muse Spark Open
(no structured output on Baseten, so the reply is parsed from JSON text), and ``box_masks_open`` segments the boxes
with SAM 3.1 open weights on Modal (``backend.perception.sam_open.segment_boxes_open``).
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

import meta_sam_parser as msp
import numpy as np

from backend.clients.cost import CostEntry, CostLedger, muse_cost
from backend.clients.meta import meta_client, with_retries
from backend.perception.sam import Instance, parse_output, segment_image
from backend.perception.tiling import merge_instances

MODEL = "muse-spark-1.3"
MAX_BOXES = 16  # SAM 3.1 object-prompt limit
REUSE_IOU = 0.9

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["boxes"], "properties": {
    "boxes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["left", "top", "right", "bottom"],
                                         "properties": {k: {"type": "integer"} for k in
                                                        ("left", "top", "right", "bottom")}}}}}

Box = tuple[int, int, int, int]  # left, top, right, bottom


def box_system(width: int, height: int) -> str:
    """System prompt for one frame size (identical to the benchmark prompt at 640x640)."""
    return (f"You find corrosion on industrial and outdoor metal. The image is {width}x{height} pixels. "
            f"List a tight bounding box around every separate visible rust or corrosion region (orange-brown "
            f"oxide, flaking, pitting, rust staining), at most {MAX_BOXES}, largest first. Coordinates are "
            f"integer pixels: left, top, right, bottom, with 0 <= left < right <= {width} and "
            f"0 <= top < bottom <= {height}. Return an empty list if there is no corrosion.")


OPEN_JSON_INSTRUCTION = (' Reply with only a JSON object and nothing else: {"boxes": [{"left": int, "top": int, '
                         '"right": int, "bottom": int}, ...]}.')
OPEN_MAX_TOKENS = 8000  # Muse Spark Open reasons before answering and has no strict decoding (RESULTS.md section 6)


def _parse_boxes(text: str) -> list[dict]:
    """Box dicts from a JSON reply; [] when the reply has no parseable JSON (fail closed: no extra candidates)."""
    from backend.verify.verifier import _extract_json
    try:
        boxes = json.loads(_extract_json(text or '{"boxes": []}')).get("boxes", [])
    except (ValueError, AttributeError):
        return []
    return [b for b in boxes if isinstance(b, dict)] if isinstance(boxes, list) else []


def propose_boxes(image: Path, width: int, height: int, *, ledger: CostLedger | None = None,
                  job: str = "box-propose", provider: str = "meta") -> list[Box]:
    """Rust boxes on one frame (Muse Spark, or Muse Spark Open with ``provider="baseten"``), clamped to the
    frame; boxes under 4 px are dropped."""
    mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
    url = f"data:{mime};base64," + base64.b64encode(image.read_bytes()).decode()
    user = {"role": "user", "content": [{"type": "text", "text": "Find the corrosion."},
                                        {"type": "image_url", "image_url": {"url": url}}]}
    if provider == "baseten":
        from backend.verify.verifier import BASETEN_MODEL, baseten_client
        model = BASETEN_MODEL
        resp = with_retries(lambda: baseten_client().chat.completions.create(
            model=model, max_tokens=OPEN_MAX_TOKENS,
            messages=[{"role": "system", "content": box_system(width, height) + OPEN_JSON_INSTRUCTION}, user]))
    else:
        model = MODEL
        resp = with_retries(lambda: meta_client().chat.completions.create(
            model=model, reasoning_effort="minimal", max_tokens=3000,
            response_format={"type": "json_schema", "json_schema": {"name": "boxes", "strict": True,
                                                                    "schema": SCHEMA}},
            messages=[{"role": "system", "content": box_system(width, height)}, user]))
    u = resp.usage
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    if ledger is not None:
        # Baseten lists Muse Spark Open at the hosted Muse Spark per-token price (docs/COST_LOG.md).
        ledger.add(CostEntry(job=job, model=model, usd=muse_cost(u.prompt_tokens, u.completion_tokens, cached),
                             input_tokens=u.prompt_tokens, cached_tokens=cached, output_tokens=u.completion_tokens))
    raw = _parse_boxes(resp.choices[0].message.content)
    # The model occasionally returns an edge a few pixels outside the frame (e.g. 642 on 640).
    boxes = [(max(0, min(width, int(b["left"]))), max(0, min(height, int(b["top"]))),
              max(0, min(width, int(b["right"]))), max(0, min(height, int(b["bottom"]))))
             for b in raw if all(k in b for k in ("left", "top", "right", "bottom"))]
    return [b for b in boxes if b[2] - b[0] >= 4 and b[3] - b[1] >= 4][:MAX_BOXES]


def box_masks(image: Path, boxes: list[Box], width: int, height: int, *, ledger: CostLedger | None = None,
              job: str = "box-sam") -> str:
    """Raw SAM 3.1 output for box prompts on one frame ('' when there are no boxes)."""
    if not boxes:
        return ""
    prompt = msp.build_object_prompt(size=(width, height), objects=[
        msp.PromptObject(id=i, prompts=[msp.FramePrompt(frame=0, box=msp.PromptBox(*b))])
        for i, b in enumerate(boxes)])
    return segment_image(image, prompt, size=(width, height), ledger=ledger, job=job).raw_output


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    return int((a & b).sum()) / max(1, int((a | b).sum()))


def merge_with_text(text: list[Instance], boxes: list[Instance]) -> list[tuple[str, Instance]]:
    """Merged instances with stable ids: a text instance's object id when reused, else ``b<k>``."""
    out = []
    for inst in merge_instances(text + boxes):
        best = max(text, key=lambda t: _iou(t.mask, inst.mask), default=None)
        if best is not None and _iou(best.mask, inst.mask) >= REUSE_IOU:
            out.append((best.object_id, best))
        else:
            out.append((f"b{inst.object_id}", inst))
    return out


def parse_box_output(raw: str, width: int, height: int) -> list[Instance]:
    return parse_output(raw, width, height) if raw else []
