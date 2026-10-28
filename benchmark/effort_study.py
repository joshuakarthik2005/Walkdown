"""Medium reasoning effort for the hosted verifier: does it beat low / minimal enough to pay for itself?

Candidates: the builder's audits (100 text + 50 box candidates; human labels) and the first ``--test-n`` text-prompt
test candidates in the low-effort journal (TP retention vs coverage labels, decision agreement with low effort).
Verdicts at medium effort are cached in VERIFY_DIR/meta/medium (same layout as verify_eval), so low, minimal and
medium are compared on identical candidates and identical prompt.

    .venv\\Scripts\\python.exe -m benchmark.effort_study --test-n 1000 --max-usd 12
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from backend.clients.cost import CostLedger
from backend.verify.verifier import verify
from benchmark.download_dataset import DATA_DIR
from benchmark.fireworks_eval import LazyCandidate, _grade_of, test_candidates
from benchmark.verifier_hardening import audit_stats, audited
from benchmark.verify_eval import VERIFY_DIR

RESULTS = Path(__file__).parent / "results"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--test-n", type=int, default=1000)
    ap.add_argument("--max-usd", type=float, required=True)
    args = ap.parse_args()
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    cache = VERIFY_DIR / "meta" / args.effort
    cache.mkdir(parents=True, exist_ok=True)
    aud = audited()
    test = test_candidates()[:args.test_n]
    stats: list[dict] = []

    def one(c) -> None:
        path = cache / (c.candidate_id.replace("#", "__") + ".json")
        if path.exists() or ledger.total() > args.max_usd:
            return
        if isinstance(c, LazyCandidate):
            c = c.load()
        v = verify(c, provider="meta", reasoning_effort=args.effort, ledger=ledger, job=f"effort-{args.effort}")
        d = asdict(v)
        d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
        path.write_text(json.dumps(d), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, [c for _, c in aud] + [c for _, c in test]))

    def acc(effort: str, cid: str):
        x = _grade_of(VERIFY_DIR / "meta" / effort / (cid.replace("#", "__") + ".json"))
        return x[1] if x else None

    res: dict = dict(effort=args.effort, audited={}, test={})
    for e in ("minimal", "low", args.effort):
        res["audited"][e] = audit_stats(aud, [acc(e, c.candidate_id) for _, c in aud])
        rows = [(r, acc(e, c.candidate_id)) for r, c in test]
        rows = [(r, a) for r, a in rows if a is not None]
        tps = [a for r, a in rows if r["label"] == "TP"]
        low = [(a, acc("low", r["id"])) for r, a in rows]
        low = [(a, b) for a, b in low if b is not None]
        res["test"][e] = dict(candidates=len(rows), tp_retention=sum(tps) / len(tps) if tps else None,
                              accepted_share=sum(a for _, a in rows) / len(rows) if rows else None,
                              agreement_with_low=sum(a == b for a, b in low) / len(low) if low else None)
    files = [cache / (c.candidate_id.replace("#", "__") + ".json") for _, c in aud + test]
    vs = [json.loads(f.read_text(encoding="utf-8")) for f in files if f.exists()]
    paid = [v for v in vs if v.get("usd")]
    res["cost"] = dict(new_usd=round(ledger.total(), 3), usd_per_candidate=statistics.mean(v["usd"] for v in paid) if paid else None,
                       reasoning_tokens_mean=statistics.mean(v["reasoning_tokens"] for v in paid) if paid else None,
                       latency_s_median=statistics.median(v["latency_s"] for v in paid) if paid else None)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"effort_study_{args.effort}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
