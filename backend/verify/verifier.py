"""Muse Spark verifier: accept or reject a SAM candidate and grade it.

Two providers, same prompt, same images, same schema:
- ``meta``: hosted ``muse-spark-1.3`` (Meta Model API), Chat Completions with
  ``response_format`` json_schema (strict) and ``reasoning_effort``, as in the
  Meta docs (structured-output, reasoning, image-understanding pages).
- ``baseten``: open-weight Muse Spark Open on Baseten. Baseten does not offer
  structured outputs for this model, so the schema goes in the prompt and the
  reply is validated with Pydantic, with one retry on invalid JSON.

The system prompt and schema are fixed and come first, so the Meta API's
automatic prefix caching can reuse them; the per-candidate content comes last.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from backend.clients.cost import CostEntry, CostLedger, muse_cost, wonder_cost
from backend.clients.meta import PROJECT_ROOT, BillingError, meta_client, with_retries
from backend.verify.crops import verifier_images
from backend.verify.schema import Grade, consistency_flags, grade_json_schema

META_MODEL = "muse-spark-1.3"
WONDER_MODEL = "muse-wonder-1.0"  # senior review (backend/verify/escalation.py)
BASETEN_MODEL = "meta-models/muse-spark-open-1026"
BASETEN_URL = "https://inference.baseten.co/v1"
BASETEN_MAX_TOKENS = 8000
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You are a corrosion inspection verifier for energy plant assets (pipes, tanks, valves, \
supports, railings). An automatic segmenter proposed a candidate region. Decide whether the region outlined \
in CYAN shows a real defect, and grade it.

You get two images:
1. A close-up crop. The candidate region is outlined in cyan.
2. A small thumbnail of the whole frame. The candidate's bounding box is drawn in cyan.

Rules:
- is_defect = true only for real corrosion or a closely related defect visible INSIDE the outline: rust \
(orange-brown oxide, scale, pitting, flaking, blistering), rust staining running from a corroding part, leak \
stains, damaged insulation or coating that exposes metal.
- is_defect = false for look-alikes: orange or red paint, brown or wet dirt, shadows, reflections, wood, soil, \
plants, rust-coloured background objects, labels, or clean metal. If the outline mostly covers non-defect \
surface, reject it.
- severity (1-5): 1 cosmetic discoloration; 2 light surface rust, no visible material loss; 3 moderate rust \
with flaking or scale over a noticeable area; 4 heavy corrosion with visible pitting or section loss, or at a \
critical spot (weld, flange, support, bolt); 5 severe: holes, through-wall loss, active leak, or a part that \
looks structurally compromised. Use 1 when is_defect is false.
- confidence: your probability (0 to 1) that is_defect is correct.
- evidence: concrete visual cues you used, where on the object the region is, how much is affected, and how \
well the cyan outline fits the actual defect (good, partial, poor).
- recommended_action: no_action, monitor, clean_and_recoat, repair, replace or urgent_inspection, consistent \
with the severity.
Judge only what is visible. Do not guess about hidden damage."""

# v2 (verifier hardening): an explicit look-alike checklist and a texture-evidence requirement. Tuned only on
# FLUX training negatives (never on the Muse Image set, public negatives or audited labels); adopted only if it
# lowers false alarms without costing more than 3 points of audited real-rust recall (docs/DECISIONS.md).
SYSTEM_PROMPT_V2 = SYSTEM_PROMPT + """

Look-alike checklist (check every item before accepting):
- Orange, red, brown or rust-coloured PAINT, primer, coatings, tape, labels, arrows: uniform colour, smooth surface, sharp painted edges -> not a defect.
- Water stains, wet patches, dirt, mud, dust, oil or soot: dark or brown but no oxide texture -> not a defect.
- Shadows, reflections, warm lighting, wood, soil, plants, copper or brass parts -> not a defect.
To accept, name at least one TEXTURE cue visible inside the outline: flaking, pitting, scaling, blistering, granular orange-brown oxide, section loss, or a stain that starts at a visibly corroding part (weld, bolt, flange, crack). Colour alone is never enough.
If the candidate was proposed by a box detector rather than the 'rust' text prompt, apply the checklist strictly: accept only with a clear texture cue."""
PROMPTS = {"v1": SYSTEM_PROMPT, "v2": SYSTEM_PROMPT_V2}

JSON_INSTRUCTION = ("\n\nReply with ONLY a JSON object, no markdown, matching this JSON schema exactly:\n"
                    + json.dumps(grade_json_schema()))


@dataclass
class Candidate:
    """A SAM candidate to verify."""

    candidate_id: str
    image: np.ndarray  # BGR full frame
    mask: np.ndarray  # bool full-frame mask
    box: tuple[int, int, int, int]
    sam_confidence: float | None = None
    source: str | None = None  # "text" or "box" (which perception path proposed it); stated to the v2 prompt only


@dataclass
class Verdict:
    """Verifier result for one candidate."""

    candidate_id: str
    provider: str
    grade: Grade | None
    flags: list[str]
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int
    usd: float | None
    latency_s: float
    attempts: int
    error: str | None = None
    raw: str = field(default="", repr=False)


@lru_cache(maxsize=1)
def baseten_client() -> OpenAI:
    """OpenAI-compatible client for Baseten Model APIs."""
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        raise BillingError("BASETEN_API_KEY missing from .env")
    return OpenAI(base_url=BASETEN_URL, api_key=key, max_retries=0, timeout=180)


FIREWORKS_URL = "https://api.fireworks.ai/inference/v1"


@lru_cache(maxsize=1)
def fireworks_client() -> OpenAI:
    """OpenAI-compatible client for Fireworks inference (key from .env, never printed)."""
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    key = os.environ.get("FIREWORKS_API_KEY")
    if not key:
        raise BillingError("FIREWORKS_API_KEY missing from .env")
    return OpenAI(base_url=FIREWORKS_URL, api_key=key, max_retries=0, timeout=300)


def _user_content(c: Candidate, prompt_version: str = PROMPT_VERSION) -> list[dict]:
    crop, thumb = verifier_images(c.image, c.mask, c.box)
    h, w = c.mask.shape
    l, t, r, b = c.box
    origin = ("segmenter prompt 'rust'" if prompt_version == "v1" or c.source != "box"
              else "proposed by a box detector (not by the 'rust' text prompt)")
    text = (f"Candidate {c.candidate_id}: {origin}"
            + (f", segmenter confidence {c.sam_confidence:.2f}" if c.sam_confidence is not None else "")
            + f". Mask covers {100 * c.mask.sum() / (h * w):.2f}% of the {w}x{h} frame; box x {l}-{r}, y {t}-{b}.")
    return [{"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": crop}},
            {"type": "image_url", "image_url": {"url": thumb}}]


def _extract_json(text: str) -> str:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def verify(c: Candidate, *, provider: str = "meta", reasoning_effort: str = "low", max_tokens: int | None = None,
           ledger: CostLedger | None = None, job: str = "verify", prompt_version: str | None = None,
           model: str | None = None) -> Verdict:
    """Verify and grade one candidate. Never raises on a bad reply; the Verdict carries the error."""
    prompt_version = prompt_version or PROMPT_VERSION
    system = PROMPTS[prompt_version]
    content = _user_content(c, prompt_version)
    if max_tokens is None:
        # Muse Spark Open reasons about twice as long and has no strict decoding; at 4,000 tokens 1.8% of replies
        # were cut off before the JSON (benchmark/RESULTS.md section 6).
        max_tokens = BASETEN_MAX_TOKENS if provider in ("baseten", "fireworks") else 4000
    if provider in ("meta", "wonder"):
        client, model = meta_client(), META_MODEL if provider == "meta" else WONDER_MODEL
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        extra = dict(response_format={"type": "json_schema", "json_schema": {
                         "name": "walkdown_grade", "strict": True, "schema": grade_json_schema()}},
                     reasoning_effort=reasoning_effort, prompt_cache_key=f"walkdown-verifier-{prompt_version}")
    elif provider == "baseten":
        client, model = baseten_client(), BASETEN_MODEL
        messages = [{"role": "system", "content": system + JSON_INSTRUCTION}, {"role": "user", "content": content}]
        extra = {}
    elif provider == "fireworks":
        # Muse Glimmer on a Fireworks on-demand deployment (``model`` = the deployment path). Same prompt and
        # JSON-in-prompt handling as Muse Spark Open; Glimmer's reasoning strength is set in the system prompt.
        if not model:
            raise ValueError("provider 'fireworks' needs model=<deployment path>")
        client = fireworks_client()
        messages = [{"role": "system", "content": f"Reasoning strength: {reasoning_effort}\n\n" + system + JSON_INSTRUCTION},
                    {"role": "user", "content": content}]
        extra = {}
    else:
        raise ValueError(f"unknown provider {provider!r}")

    tokens = dict(input=0, cached=0, output=0, reasoning=0)
    t0 = time.perf_counter()
    grade, error, raw, attempts = None, None, "", 0
    for attempts in (1, 2):
        resp = with_retries(lambda: client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, **extra))
        u = resp.usage
        tokens["input"] += u.prompt_tokens or 0
        tokens["output"] += u.completion_tokens or 0
        tokens["cached"] += getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        tokens["reasoning"] += getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        raw = resp.choices[0].message.content or ""
        finish = resp.choices[0].finish_reason
        try:
            grade = Grade.model_validate_json(_extract_json(raw))
            error = None
            break
        except (ValidationError, ValueError) as err:
            error = f"invalid reply (finish_reason={finish}): {str(err)[:200]}"
            if finish == "length":
                break  # a retry with the same budget would truncate again
    latency = time.perf_counter() - t0
    # Baseten lists Muse Spark Open at the same per-token price as hosted Muse Spark (docs/COST_LOG.md). A Fireworks
    # on-demand deployment bills per GPU hour, recorded by the caller, so per-call cost is 0 here.
    usd = 0.0 if provider == "fireworks" else (wonder_cost if provider == "wonder" else muse_cost)(
        tokens["input"], tokens["output"], tokens["cached"])
    if ledger is not None:
        ledger.add(CostEntry(job=job, model=model, usd=usd or 0.0, input_tokens=tokens["input"],
                             cached_tokens=tokens["cached"], output_tokens=tokens["output"],
                             reasoning_tokens=tokens["reasoning"]))
    return Verdict(candidate_id=c.candidate_id, provider=provider, grade=grade,
                   flags=consistency_flags(grade) if grade else ["no_valid_grade"],
                   input_tokens=tokens["input"], cached_tokens=tokens["cached"], output_tokens=tokens["output"],
                   reasoning_tokens=tokens["reasoning"], usd=usd, latency_s=latency, attempts=attempts,
                   error=error, raw=raw)
