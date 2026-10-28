"""Re-verify only the candidates whose verify_scale reply was invalid, with a larger output budget.

Reads the verify_scale journal for a split and provider, picks rows with no valid grade, and verifies those
candidates again with ``--max-tokens`` (cached separately under ``<effort>-retry<max_tokens>``, so the
original verdicts are kept). Reports the invalid rate before and after the retry, and writes the retry
outcome per candidate to ``results/verify_retry_<split>_<provider>_<effort>.json``.

    .venv\\Scripts\\python.exe -m benchmark.verify_retry test --provider baseten --max-tokens 8000 --max-usd 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.clients.cost import CostLedger
from backend.perception.sam import parse_output
from benchmark.download_dataset import DATA_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR
from benchmark.verify_eval import _cached_verify
from benchmark.verify_scale import journal_path, read_journal

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--provider", choices=("meta", "baseten"), default="baseten")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--max-tokens", type=int, required=True)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--threads", type=int, default=6)
    args = ap.parse_args()

    done = read_journal(journal_path(args.split, args.effort, args.provider))
    rows = [r | {"image": rel} for rel, rs in done.items() for r in rs]
    invalid = [r for r in rows if not r["valid"]]
    print(f"{len(rows)} candidates, {len(invalid)} invalid ({len(invalid) / len(rows):.2%}); retrying at "
          f"max_tokens={args.max_tokens}", flush=True)

    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")

    def run(r: dict):
        if ledger.total() > args.max_usd:
            return None
        stem, obj = r["id"].split("#")
        inst = next(i for i in parse_output((SAM_DIR / "rust" / (stem + ".txt")).read_text(encoding="utf-8"), 640, 640)
                    if i.object_id == obj)
        try:
            return _cached_verify(dict(id=r["id"], image=r["image"], instance=inst), args.provider, args.effort,
                                  ledger, suffix=f"-retry{args.max_tokens}", max_tokens=args.max_tokens)
        except Exception as err:  # noqa: BLE001 - report and continue; a rerun retries uncached ones
            print(f"{r['id']}: {type(err).__name__}: {str(err)[:150]}", flush=True)
            return None

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        verdicts = list(pool.map(run, invalid))

    retried = [(r, v) for r, v in zip(invalid, verdicts) if v is not None]
    fixed = [(r, v) for r, v in retried if v.grade is not None]
    still_invalid = len(invalid) - len(fixed)
    out = dict(
        split=args.split, provider=args.provider, effort=args.effort, max_tokens=args.max_tokens,
        candidates=len(rows), invalid_before=len(invalid), invalid_rate_before=len(invalid) / len(rows),
        retried=len(retried), fixed=len(fixed), invalid_after=still_invalid,
        invalid_rate_after=still_invalid / len(rows),
        fixed_accepted=sum(v.grade.is_defect for _, v in fixed),
        fixed_label_counts={k: sum(r["label"] == k for r, _ in fixed) for k in ("TP", "FP", "ambiguous")},
        usd=ledger.total(), usd_per_retry=ledger.total() / len(retried) if retried else None,
        latency_s_median=statistics.median(v.latency_s for _, v in retried) if retried else None,
        per_candidate={r["id"]: (dict(is_defect=v.grade.is_defect, severity=v.grade.severity) if v and v.grade
                                 else None) for r, v in zip(invalid, verdicts)},
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"verify_retry_{args.split}_{args.provider}_{args.effort}.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_candidate"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
