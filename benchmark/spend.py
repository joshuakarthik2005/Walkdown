r"""Spend per provider from the local cost ledger since a start time (overnight caps).

    .venv\Scripts\python.exe -m benchmark.spend [start_epoch]
"""

from __future__ import annotations

import json
import sys

from benchmark.download_dataset import DATA_DIR

LEDGER = DATA_DIR / "runs" / "cost_ledger.jsonl"


def provider(model: str) -> str:
    m = model.lower()
    if "modal" in m:
        return "modal"
    if "fireworks" in m or "glimmer" in m:
        return "fireworks"
    if "muse-spark-open" in m or "baseten" in m:
        return "baseten"
    return "meta"


def since(start: float) -> dict[str, float]:
    out = {"meta": 0.0, "baseten": 0.0, "modal": 0.0, "fireworks": 0.0}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("timestamp", 0) >= start:
            out[provider(r["model"])] += r.get("usd") or 0.0
    return {k: round(v, 3) for k, v in out.items()}


if __name__ == "__main__":
    start = float(sys.argv[1]) if len(sys.argv) > 1 else float((DATA_DIR / "runs" / "overnight_start.txt").read_text())
    print(json.dumps(since(start)))
