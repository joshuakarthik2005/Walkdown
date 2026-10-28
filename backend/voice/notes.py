"""F4 voice notes: Muse Voice Transcribe on an inspector's recording, then structured extraction.

1. ``transcribe``: POST /v1/asr/transcribe (multipart: a JSON ``request`` part and a WAV ``audio`` part), as in
   https://dev.meta.ai/docs/speech-to-text. The API takes mono integer PCM WAV at 16 or 24 kHz; other WAVs are
   converted locally (downmix, linear resample to 16 kHz, 16-bit). Other formats must be converted first.
   Plant vocabulary is passed as ``keywords`` to bias recognition.
2. ``extract``: Muse Spark with a strict JSON schema turns the transcript into a ``VoiceNote``: asset tag, line
   service, defect remarks and follow-ups. Fields not said in the recording stay null or empty; the prompt
   forbids inferring them.
"""

from __future__ import annotations

import io
import json
import os
import wave
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from backend.clients.cost import CostEntry, CostLedger, muse_cost, voice_cost
from backend.clients.meta import PROJECT_ROOT, meta_client, with_retries
from backend.planner.models import ServiceType

ASR_URL = "https://api.meta.ai/v1/asr/transcribe"
ASR_MODEL = "muse-voice-transcribe-1.0"
KEYWORDS = ["LPG", "hydrogen", "crude", "steam", "cooling water", "fire water", "nitrogen", "flange", "weld",
            "pipe support", "insulation", "corrosion", "pitting", "scale", "leak", "valve", "tank", "header"]


def to_api_wav(data: bytes) -> bytes:
    """Mono 16-bit PCM WAV at 16 or 24 kHz, as the API requires (converted if needed)."""
    with wave.open(io.BytesIO(data)) as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if ch == 1 and width == 2 and rate in (16000, 24000):
        return data
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    x = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    x = (x - 128) / 128 if width == 1 else x / float(np.iinfo(dtype).max)
    x = x.reshape(-1, ch).mean(1)
    target = 16000
    t = np.arange(int(len(x) * target / rate)) * rate / target
    y = np.interp(t, np.arange(len(x)), x)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(target)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return out.getvalue()


def transcribe(audio: bytes, *, ledger: CostLedger | None = None, job: str = "voice-transcribe",
               client: httpx.Client | None = None) -> dict:
    """Transcript and duration of one WAV recording."""
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    settings = dict(model=ASR_MODEL, audioEncoding="WAV", mode="PUSH_TO_TALK", languageBias=["English"],
                    keywords=KEYWORDS)
    files = {"request": (None, json.dumps(settings), "application/json"),
             "audio": ("note.wav", to_api_wav(audio), "audio/wav")}
    http = client or httpx.Client(timeout=300)
    resp = http.post(ASR_URL, files=files, headers={"Authorization": f"Bearer {os.environ['MODEL_API_KEY']}"})
    if resp.status_code != 200:
        raise RuntimeError(f"transcribe: HTTP {resp.status_code} {resp.text[:300]}")
    out = resp.json()
    ms = int(out.get("audioDurationMs") or 0)
    if ledger is not None:
        ledger.add(CostEntry(job=job, model=ASR_MODEL, usd=voice_cost(ms)))
    return dict(transcript=out.get("transcript", ""), audio_ms=ms)


class DefectRemark(BaseModel):
    """One defect the inspector talked about."""

    model_config = ConfigDict(extra="forbid")
    location: str = Field(description="Where on the asset, as said (e.g. 'second flange from the pump').")
    description: str = Field(description="What the inspector said about it, close to their words.")
    severity_words: str = Field(description="The inspector's own severity wording ('heavy', 'light'), or ''.")


class VoiceNote(BaseModel):
    """What an inspector said about the asset, structured."""

    model_config = ConfigDict(extra="forbid")
    asset_tag: str | None = Field(description="Asset tag as said (e.g. 'P-101'), or null if not said.")
    line_service: ServiceType | None = Field(description="Line service if said, else null.")
    remarks: list[DefectRemark]
    follow_ups: list[str] = Field(description="Actions the inspector asked for (e.g. 'UT thickness check').")
    summary: str = Field(description="One sentence summary of the note.")


EXTRACT_PROMPT = """You turn a plant inspector's spoken walkdown note (a speech-to-text transcript) into \
structured fields. Use only what the transcript says. If the asset tag or line service is not said, return null; \
never infer them from context. Write asset tags as letters, digits and hyphens (e.g. "P one oh one" becomes \
"P-101") only when it is clearly a tag. line_service must be one of: lpg, crude, hydrogen, hydrocarbon_vapour, \
chemical, steam, cooling_water, fire_water, air_nitrogen, or null."""


def note_schema() -> dict:
    """Strict-mode schema (every key required; nullable fields as type unions)."""
    remark = {"type": "object", "additionalProperties": False, "required": ["location", "description", "severity_words"],
              "properties": {k: {"type": "string"} for k in ("location", "description", "severity_words")}}
    return {"type": "object", "additionalProperties": False,
            "required": ["asset_tag", "line_service", "remarks", "follow_ups", "summary"],
            "properties": {"asset_tag": {"type": ["string", "null"]},
                           "line_service": {"type": ["string", "null"], "enum": [s.value for s in ServiceType] + [None]},
                           "remarks": {"type": "array", "items": remark},
                           "follow_ups": {"type": "array", "items": {"type": "string"}},
                           "summary": {"type": "string"}}}


def extract(transcript: str, *, ledger: CostLedger | None = None, job: str = "voice-extract") -> VoiceNote:
    """Structured note from a transcript (Muse Spark, strict JSON schema, minimal reasoning)."""
    resp = with_retries(lambda: meta_client().chat.completions.create(
        model="muse-spark-1.3", reasoning_effort="minimal", max_tokens=2000,
        response_format={"type": "json_schema", "json_schema": {"name": "voice_note", "strict": True,
                                                                "schema": note_schema()}},
        messages=[{"role": "system", "content": EXTRACT_PROMPT},
                  {"role": "user", "content": f"Transcript:\n{transcript}"}]))
    u = resp.usage
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    if ledger is not None:
        ledger.add(CostEntry(job=job, model="muse-spark-1.3", usd=muse_cost(u.prompt_tokens, u.completion_tokens, cached),
                             input_tokens=u.prompt_tokens, cached_tokens=cached, output_tokens=u.completion_tokens))
    return VoiceNote.model_validate_json(resp.choices[0].message.content or "{}")


def process(audio: bytes, *, ledger: CostLedger | None = None) -> dict:
    """Transcribe and extract one recording; returns transcript, duration and the structured note."""
    t = transcribe(audio, ledger=ledger)
    note = extract(t["transcript"], ledger=ledger) if t["transcript"].strip() else None
    return dict(transcript=t["transcript"], audio_ms=t["audio_ms"], note=note.model_dump(mode="json") if note else None)


def process_file(path: Path, *, ledger: CostLedger | None = None) -> dict:
    return process(path.read_bytes(), ledger=ledger)
