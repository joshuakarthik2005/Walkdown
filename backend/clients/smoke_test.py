"""Smoke test for the Meta Model API.

Loads MODEL_API_KEY from .env (never printed), makes one tiny muse-spark-1.3
call through the Responses API, and prints only the reply and token usage.

Run from the project root:
    .venv\\Scripts\\python.exe -m backend.clients.smoke_test
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"

# Official prices, USD per 1M tokens.
PRICE_INPUT = 1.25
PRICE_OUTPUT = 4.25


def main() -> int:
    """Run one minimal call and report reply, usage and estimated cost."""
    # override=True: .env always wins over a stale key in the shell environment.
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    present = {name: bool(os.environ.get(name)) for name in ("MODEL_API_KEY", "BASETEN_API_KEY")}
    print("Env variables present:", present)
    if not present["MODEL_API_KEY"]:
        print("MODEL_API_KEY missing from .env")
        return 1

    client = OpenAI(base_url=BASE_URL, api_key=os.environ["MODEL_API_KEY"])
    response = client.responses.create(
        model=MODEL,
        input="Reply with exactly: Walkdown smoke test OK",
        # Reasoning tokens count toward max_output_tokens; keep effort minimal
        # so the visible reply is not starved.
        reasoning={"effort": "minimal"},
        max_output_tokens=500,
    )

    usage = response.usage
    details = getattr(usage, "output_tokens_details", None)
    reasoning_tokens = getattr(details, "reasoning_tokens", None)
    cost = (usage.input_tokens * PRICE_INPUT + usage.output_tokens * PRICE_OUTPUT) / 1_000_000
    print("Status:", response.status)
    print("Reply:", response.output_text.strip())
    print(
        f"Usage: input={usage.input_tokens} output={usage.output_tokens} "
        f"(reasoning={reasoning_tokens}) total={usage.total_tokens}"
    )
    print(f"Estimated cost: ${cost:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
