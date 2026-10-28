"""API prices and a cost ledger.

Prices are the official list prices (https://dev.meta.ai/docs/pricing-rate-limits,
checked 2026-10-27). Every billable call is recorded with what it was billed
on, so a job's cost can be measured from real usage before scaling up.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# USD
SAM_PER_IMAGE = 2.50 / 1000
SAM_PER_VIDEO_FRAME = 0.20 / 1000
SAM_MIN_VIDEO_FRAMES = 50
MUSE_INPUT_PER_TOKEN = 1.25 / 1_000_000
MUSE_CACHED_INPUT_PER_TOKEN = 0.15 / 1_000_000
MUSE_OUTPUT_PER_TOKEN = 4.25 / 1_000_000
WONDER_INPUT_PER_TOKEN = 4.00 / 1_000_000
WONDER_CACHED_INPUT_PER_TOKEN = 0.20 / 1_000_000
WONDER_OUTPUT_PER_TOKEN = 20.00 / 1_000_000
VOICE_PER_HOUR = 0.18  # muse-voice-transcribe-1.0, metered in whole seconds, rounded down


def sam_image_cost(images: int = 1) -> float:
    """Cost of SAM image requests."""
    return images * SAM_PER_IMAGE


def sam_video_cost(frames: int) -> float:
    """Cost of one SAM video request (billed for at least 50 frames)."""
    return max(frames, SAM_MIN_VIDEO_FRAMES) * SAM_PER_VIDEO_FRAME


def muse_cost(input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """Cost of one Muse Spark call; reasoning tokens are already counted in output_tokens."""
    fresh = input_tokens - cached_tokens
    return (fresh * MUSE_INPUT_PER_TOKEN + cached_tokens * MUSE_CACHED_INPUT_PER_TOKEN
            + output_tokens * MUSE_OUTPUT_PER_TOKEN)


def voice_cost(audio_ms: int) -> float:
    """Cost of transcribing ``audio_ms`` of audio with Muse Voice Transcribe."""
    return (audio_ms // 1000) * VOICE_PER_HOUR / 3600


def wonder_cost(input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """Cost of one Muse Wonder call (muse-wonder-1.0, Standard mode)."""
    fresh = input_tokens - cached_tokens
    return (fresh * WONDER_INPUT_PER_TOKEN + cached_tokens * WONDER_CACHED_INPUT_PER_TOKEN
            + output_tokens * WONDER_OUTPUT_PER_TOKEN)


@dataclass
class CostEntry:
    """One billable call."""

    job: str
    model: str
    usd: float
    images: int = 0
    frames: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    timestamp: float = field(default_factory=time.time)


class CostLedger:
    """Thread-safe running total, optionally appended to a JSONL file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.entries: list[CostEntry] = []
        self._lock = threading.Lock()

    def add(self, entry: CostEntry) -> CostEntry:
        """Record a call."""
        with self._lock:
            self.entries.append(entry)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # One unbuffered O_APPEND write per record, so parallel processes don't interleave lines.
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0))
                try:
                    os.write(fd, (json.dumps(asdict(entry)) + "\n").encode("utf-8"))
                finally:
                    os.close(fd)
        return entry

    def total(self, job: str | None = None) -> float:
        """Total USD, optionally for one job."""
        return sum(e.usd for e in self.entries if job is None or e.job == job)

    def summary(self, job: str | None = None) -> dict:
        """Aggregate counts and cost."""
        es = [e for e in self.entries if job is None or e.job == job]
        keys = ("images", "frames", "input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens")
        out = {k: sum(getattr(e, k) for e in es) for k in keys}
        out.update(calls=len(es), usd=sum(e.usd for e in es))
        return out


def read_ledger(path: Path) -> list[dict]:
    """All well-formed records in a ledger file (malformed lines from older concurrent writes are skipped)."""
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
