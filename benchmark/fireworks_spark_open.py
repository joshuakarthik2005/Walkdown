"""Muse Spark Open on two hosts: Fireworks serverless vs Baseten, on the same 100 test candidates.

Same model family (Fireworks lists ``accounts/fireworks/models/muse-spark-open``; Baseten serves
``meta-models/muse-spark-open-1026``), same prompt and images, schema in the prompt, max_tokens 8,000. The Baseten
verdicts are the cached RESULTS 6 verdicts (4,000 tokens; the 8,000-token retry where the first reply was invalid),
so only the Fireworks side is paid. Reports decision agreement, severity agreement, invalid replies, latency, cost.

    .venv\\Scripts\\python.exe -m benchmark.fireworks_spark_open --n 100
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from backend.clients.cost import CostEntry, CostLedger, muse_cost
from backend.verify.verifier import verify
from benchmark.download_dataset import DATA_DIR
from benchmark.fireworks_eval import test_candidates
from benchmark.verify_eval import VERIFY_DIR

MODEL = "accounts/fireworks/models/muse-spark-open"
RESULTS = Path(__file__).parent / "results"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    cache = VERIFY_DIR / "fireworks" / "spark-open-serverless"
    cache.mkdir(parents=True, exist_ok=True)
    # every 50th test candidate: spread over images and coverage labels
    picked = [x for x in test_candidates()[::50]][:args.n]

    def one(item) -> None:
        row, lazy = item
        path = cache / (lazy.candidate_id.replace("#", "__") + ".json")
        if path.exists():
            return
        v = verify(lazy.load(), provider="fireworks", model=MODEL, job="fireworks-spark-open")
        d = asdict(v)
        d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
        # serverless is billed per token at the listed Muse Spark Open rates (docs.fireworks.ai/serverless/pricing)
        d["usd"] = muse_cost(v.input_tokens, v.output_tokens, v.cached_tokens)
        ledger.add(CostEntry(job="fireworks-spark-open", model=f"fireworks {MODEL}", usd=d["usd"],
                             input_tokens=v.input_tokens, output_tokens=v.output_tokens))
        path.write_text(json.dumps(d), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, picked))

    rows = []
    for row, lazy in picked:
        n = lazy.candidate_id.replace("#", "__") + ".json"
        fw = json.loads((cache / n).read_text(encoding="utf-8"))
        bpath = next((p for p in (VERIFY_DIR / "baseten" / "low-retry8000" / n, VERIFY_DIR / "baseten" / "low" / n)
                      if p.exists()), None)
        bt = json.loads(bpath.read_text(encoding="utf-8")) if bpath else None
        rows.append((row, fw, bt))
    both = [(f["grade"], b["grade"]) for _, f, b in rows if b and f["grade"] and b["grade"]]
    res = dict(n=len(rows), model=MODEL,
               fireworks_invalid=sum(f["grade"] is None for _, f, _ in rows),
               baseten_invalid=sum(b is not None and b["grade"] is None for _, _, b in rows),
               decision_agreement=sum(a["is_defect"] == b["is_defect"] for a, b in both) / len(both) if both else None,
               severity_exact=sum(a["severity"] == b["severity"] for a, b in both) / len(both) if both else None,
               severity_within_1=sum(abs(a["severity"] - b["severity"]) <= 1 for a, b in both) / len(both) if both else None,
               fireworks_accept_share=sum((f["grade"] or {}).get("is_defect", True) for _, f, _ in rows) / len(rows),
               fireworks_latency_s_median=statistics.median(f["latency_s"] for _, f, _ in rows),
               baseten_latency_s_median=statistics.median(b["latency_s"] for _, _, b in rows if b),
               fireworks_usd_per_candidate=statistics.mean(f["usd"] for _, f, _ in rows),
               baseten_usd_per_candidate=statistics.mean((b["usd"] or 0) for _, _, b in rows if b))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "fireworks_vs_baseten_spark_open.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
