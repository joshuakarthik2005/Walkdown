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
    load_dotenv(PROJECT_ROOT / ".env")
    present = {name: bool(os.environ.get(name)) for name in ("MODEL_API_KEY", "BASETEN_API_KEY")}
    print("Env variables present:", present)
    if not present["MODEL_API_KEY"]:
        print("MODEL_API_KEY missing from .env")
        return 1

    client = OpenAI(base_url=BASE_URL, api_key=os.environ["MODEL_API_KEY"])
    response = client.responses.create(
        model=MODEL,
        input="Reply with exactly: Walkdown smoke test OK",
        max_output_tokens=200,
    )

    usage = response.usage
    cost = (usage.input_tokens * PRICE_INPUT + usage.output_tokens * PRICE_OUTPUT) / 1_000_000
    print("Reply:", response.output_text.strip())
    print(f"Usage: input={usage.input_tokens} output={usage.output_tokens} total={usage.total_tokens}")
    print(f"Estimated cost: ${cost:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
