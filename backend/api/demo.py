"""Public demo mode: configuration from the environment, a global daily spend cap and per-IP rate limits.

With ``DEMO_MODE=true`` the API is safe to expose to the public:
- runs on the sample walkdowns use cached perception and verification only (``live`` is forced off);
- uploads are limited in size and duration; On-prem (GPU) runs are off, finished examples load instantly;
- every paid call (agent turns, fresh inference, voice notes, replans, copilot questions) counts toward one
  global daily spend cap across all providers; once it is reached those endpoints answer with a friendly
  "demo budget reached" message and the samples' finished examples keep working;
- per-IP rate limits on every endpoint that can spend money.

API keys are only read from server-side environment variables (backend/clients); nothing here exposes them.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request

from backend.clients.cost import CostEntry, CostLedger


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class DemoConfig:
    """Settings for the public demo, read from the environment."""

    enabled: bool = False
    daily_cap_usd: float = 5.0
    max_upload_mb: int = 50
    max_duration_s: float = 60.0
    max_photos: int = 20
    max_runs: int = 20  # runs held in memory (about 7 MB each; the free host has 512 MB)
    # requests per IP per hour, by action
    limits: dict[str, int] = field(default_factory=lambda: dict(run=6, upload=4, voice=6, ask=20, change=10, example=60))
    cors_origins: list[str] = field(default_factory=list)
    public_api_url: str = ""

    @classmethod
    def from_env(cls) -> "DemoConfig":
        c = cls(enabled=_flag("DEMO_MODE"),
                daily_cap_usd=float(os.environ.get("DEMO_DAILY_CAP_USD", "5")),
                max_upload_mb=int(os.environ.get("DEMO_MAX_UPLOAD_MB", "50")),
                max_duration_s=float(os.environ.get("DEMO_MAX_DURATION_S", "60")),
                max_runs=int(os.environ.get("DEMO_MAX_RUNS", "20")),
                cors_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
                public_api_url=os.environ.get("PUBLIC_API_URL", "").rstrip("/"))
        for action in c.limits:
            env = os.environ.get(f"DEMO_LIMIT_{action.upper()}_PER_HOUR")
            if env:
                c.limits[action] = int(env)
        return c


BUDGET_MESSAGE = ("The public demo's daily budget is used up. Open a finished example or run a sample walkdown "
                  "(cached results), or try again tomorrow.")


class BudgetExceeded(RuntimeError):
    """Raised when a paid call would go past the daily demo cap."""

    def __init__(self) -> None:
        super().__init__(BUDGET_MESSAGE)


class SpendGuard:
    """Global spend per UTC day across all providers, persisted to disk so a restart keeps the count."""

    def __init__(self, cap_usd: float, state_dir: Path | None = None, clock=time.time) -> None:
        self.cap = cap_usd
        self.state_dir = state_dir
        self.clock = clock
        self._lock = threading.Lock()
        self._day, self._spent = self._today(), 0.0
        self._load()

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).strftime("%Y-%m-%d")

    def _file(self) -> Path | None:
        return self.state_dir / f"spend_{self._day}.json" if self.state_dir else None

    def _load(self) -> None:
        f = self._file()
        if f and f.exists():
            try:
                self._spent = float(json.loads(f.read_text(encoding="utf-8"))["usd"])
            except (ValueError, KeyError, OSError):
                self._spent = 0.0

    def _roll(self) -> None:
        if self._today() != self._day:
            self._day, self._spent = self._today(), 0.0
            self._load()

    def spent(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    def remaining(self) -> float:
        return max(0.0, self.cap - self.spent())

    def exhausted(self) -> bool:
        return self.remaining() <= 0.0

    def check(self) -> None:
        """Refuse new paid work once the cap is reached (HTTP 429 with a friendly message)."""
        if self.exhausted():
            raise HTTPException(429, BUDGET_MESSAGE)

    def add(self, usd: float) -> None:
        with self._lock:
            self._roll()
            self._spent += usd
            f = self._file()
            if f:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(dict(day=self._day, usd=round(self._spent, 6), cap=self.cap)), encoding="utf-8")


class GuardedLedger(CostLedger):
    """A run's cost ledger that also charges the global demo budget and stops the run once it is spent."""

    def __init__(self, path: Path | None, guard: SpendGuard) -> None:
        super().__init__(path)
        self.guard = guard

    def add(self, entry: CostEntry) -> CostEntry:
        out = super().add(entry)
        self.guard.add(entry.usd)
        if self.guard.exhausted():
            raise BudgetExceeded()  # the call is paid for already; no further calls in this run
        return out


class RateLimiter:
    """Sliding one-hour window per (client IP, action)."""

    def __init__(self, limits: dict[str, int], window_s: float = 3600.0, clock=time.time) -> None:
        self.limits = limits
        self.window = window_s
        self.clock = clock
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, ip: str, action: str) -> None:
        limit = self.limits.get(action)
        if not limit:
            return
        now = self.clock()
        with self._lock:
            q = self._hits[(ip, action)]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= limit:
                wait_min = max(1, int((self.window - (now - q[0])) // 60) + 1)
                raise HTTPException(429, f"Too many requests from your connection for this action. Try again in about "
                                         f"{wait_min} min, or open a finished example meanwhile.")
            q.append(now)


def client_ip(request: Request) -> str:
    """First address in X-Forwarded-For (set by the hosting proxy), else the socket peer."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
