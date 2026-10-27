"""Meta Model API client with retries.

The key is read from .env with ``override=True`` so a stale shell variable can
never win. It is never printed or logged.
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import openai
from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://api.meta.ai/v1"

T = TypeVar("T")


class BillingError(RuntimeError):
    """Payment, quota, restriction or auth problem: stop and report, never retry."""


@lru_cache(maxsize=1)
def meta_client() -> OpenAI:
    """OpenAI-compatible client for the Meta Model API (SDK retries off; ``with_retries`` handles them)."""
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise BillingError("MODEL_API_KEY missing from .env")
    return OpenAI(base_url=BASE_URL, api_key=key, max_retries=0, timeout=180)


def with_retries(call: Callable[[], T], *, attempts: int = 5, base_delay: float = 1.0) -> T:
    """Run ``call`` with exponential backoff on rate limits, timeouts and 5xx errors.

    Auth, permission and payment errors raise ``BillingError`` at once; other
    4xx errors (bad request) are raised unchanged, since retrying cannot help.
    """
    for attempt in range(attempts):
        try:
            return call()
        except (openai.AuthenticationError, openai.PermissionDeniedError) as err:
            raise BillingError(f"{type(err).__name__}: HTTP {err.status_code}") from None
        except openai.APIStatusError as err:
            if err.status_code == 402:
                raise BillingError("HTTP 402 payment required") from None
            retryable = err.status_code == 429 or err.status_code >= 500
            if not retryable or attempt == attempts - 1:
                raise
        except (openai.APITimeoutError, openai.APIConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(base_delay * 2 ** attempt + random.uniform(0, base_delay))
    raise AssertionError("unreachable")
