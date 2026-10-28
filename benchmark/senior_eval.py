"""F1: measure senior review (Muse Wonder) on the test candidates the first pass escalates.

Takes every text-only test candidate whose cached first-pass grade (hosted Muse Spark, low effort) escalates
(severity >= 4 accepted, or confidence < 0.6), sends it to Muse Wonder with the same prompt, images and
schema, and reports: how often Wonder changes the decision or the severity, agreement with the GT-coverage
labels before and after (TP/FP only; ambiguous excluded), invalid replies, cost and latency. Verdicts are
cached under WALKDOWN_DATA_DIR/runs/verify/wonder/<effort>/. Resumable; stops at ``--max-usd``.

    .venv\\Scripts\\python.exe -m benchmark.senior_eval test --limit 50 --max-usd 2
    .venv\\Scripts\\python.exe -m benchmark.senior_eval test --max-usd 14
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
from benchmark.verify_eval import VERIFY_DIR, _cached_verify
from benchmark.verify_scale import journal_path, read_journal
from backend.verify.escalation import escalation_reason
from backend.verify.schema import Grade

RESULTS_DIR = Path(__file__).parent / "results"


def first_grade(cid: str) -> Grade | None:
    d = json.loads((VERIFY_DIR / "meta" / "low" / (cid.replace("#", "__") + ".json")).read_text(encoding="utf-8"))
    return Grade.model_validate(d["grade"]) if d["grade"] else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--threads", type=int, default=6)
    args = ap.parse_args()

    rows = [r | {"image": rel} for rel, rs in read_journal(journal_path(args.split, "low")).items() for r in rs]
    esc = []
    for r in sorted(rows, key=lambda r: r["id"]):
        g = first_grade(r["id"])
        reason = escalation_reason(g)
        if reason:
            esc.append(dict(row=r, first=g, reason=reason))
    todo = esc[:args.limit] if args.limit else esc
    print(f"{len(rows)} first-pass verdicts, {len(esc)} escalate ({len(esc) / len(rows):.1%}); running {len(todo)}",
          flush=True)

    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    spent_before = ledger.total()

    def run(e: dict):
        if ledger.total() - spent_before > args.max_usd:
            return None
        r = e["row"]
        stem, obj = r["id"].split("#")
        # Masks are decoded per candidate and not kept (low memory: a full-frame bool mask is 400 KB).
        inst = next(i for i in parse_output((SAM_DIR / "rust" / (stem + ".txt")).read_text(encoding="utf-8"), 640, 640)
                    if i.object_id == obj)
        cand = dict(id=r["id"], image=r["image"], instance=inst)
        try:
            return _cached_verify(cand, "wonder", args.effort, ledger)
        except Exception as err:  # noqa: BLE001 - report and continue; rerun retries (cached ones are kept)
            print(f"{r['id']}: {type(err).__name__}: {str(err)[:150]}", flush=True)
            return None

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        verdicts = list(pool.map(run, todo))

    done = [(e, v) for e, v in zip(todo, verdicts) if v is not None]
    valid = [(e, v) for e, v in done if v.grade is not None]
    labelled = [(e, v) for e, v in valid if e["row"]["label"] in ("TP", "FP")]

    def correct(is_defect: bool, label: str) -> bool:
        return is_defect == (label == "TP")

    both_defect = [(e, v) for e, v in valid if e["first"].is_defect and v.grade.is_defect]
    out = dict(
        split=args.split, effort=args.effort, first_pass_verdicts=len(rows), escalated=len(esc),
        escalation_rate=len(esc) / len(rows), reviewed=len(done), invalid_replies=len(done) - len(valid),
        reasons=dict(severity=sum(e["reason"].startswith("severity") for e, _ in done),
                     confidence=sum(e["reason"].startswith("confidence") for e, _ in done)),
        changed_decision=sum(e["first"].is_defect != v.grade.is_defect for e, v in valid),
        changed_decision_rate=(sum(e["first"].is_defect != v.grade.is_defect for e, v in valid) / len(valid)) if valid else None,
        accepted_to_rejected=sum(e["first"].is_defect and not v.grade.is_defect for e, v in valid),
        rejected_to_accepted=sum(not e["first"].is_defect and v.grade.is_defect for e, v in valid),
        changed_severity_among_both_accepted=sum(e["first"].severity != v.grade.severity for e, v in both_defect),
        both_accepted=len(both_defect),
        mean_severity_change=(statistics.mean(v.grade.severity - e["first"].severity for e, v in both_defect)
                              if both_defect else None),
        gt_labelled=len(labelled),
        gt_label_counts={k: sum(e["row"]["label"] == k for e, _ in labelled) for k in ("TP", "FP")},
        gt_agreement_first=(sum(correct(e["first"].is_defect, e["row"]["label"]) for e, _ in labelled) / len(labelled)
                            if labelled else None),
        gt_agreement_senior=(sum(correct(v.grade.is_defect, e["row"]["label"]) for e, v in labelled) / len(labelled)
                             if labelled else None),
        tp_retention_first=_share([e["first"].is_defect for e, v in labelled if e["row"]["label"] == "TP"]),
        tp_retention_senior=_share([v.grade.is_defect for e, v in labelled if e["row"]["label"] == "TP"]),
        fp_rejection_first_NOT_RELIABLE=_share([not e["first"].is_defect for e, v in labelled if e["row"]["label"] == "FP"]),
        fp_rejection_senior_NOT_RELIABLE=_share([not v.grade.is_defect for e, v in labelled if e["row"]["label"] == "FP"]),
        usd_total=sum(v.usd or 0 for _, v in done),
        usd_per_review=statistics.mean(v.usd or 0 for _, v in done) if done else None,
        latency_s_median=statistics.median(v.latency_s for _, v in done) if done else None,
        latency_s_p90=(sorted(v.latency_s for _, v in done)[int(0.9 * (len(done) - 1))] if done else None),
        reasoning_tokens_mean=statistics.mean(v.reasoning_tokens for _, v in done) if done else None,
        new_spend_this_run=ledger.total() - spent_before,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"senior_eval_{args.split}_{args.effort}" + (f"_n{args.limit}" if args.limit else "")
    (RESULTS_DIR / f"{name}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def _share(xs: list[bool]) -> float | None:
    return sum(xs) / len(xs) if xs else None


if __name__ == "__main__":
    sys.exit(main())
