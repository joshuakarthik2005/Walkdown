"""Verifier precision/recall against the builder's audited labels, next to the GT-coverage labels.

Uses the audit sample and labels from benchmark.label_app and the cached
verifier verdicts (low effort). 'unsure' audited labels are excluded.

    .venv\\Scripts\\python.exe -m benchmark.audit_report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from benchmark.label_app import SAMPLE_PATH, read_labels
from benchmark.verify_eval import VERIFY_DIR

OUT = Path(__file__).parent / "results" / "verify_audit.json"


def _pr(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs of (truth_is_rust, verifier_accepted)."""
    tp = sum(t and a for t, a in pairs)
    fp = sum(a and not t for t, a in pairs)
    fn = sum(t and not a for t, a in pairs)
    tn = sum(not t and not a for t, a in pairs)
    return dict(n=len(pairs), positives=tp + fn, negatives=fp + tn,
                precision=tp / (tp + fp) if tp + fp else None, recall=tp / (tp + fn) if tp + fn else None,
                negatives_rejected=tn / (fp + tn) if fp + tn else None, tp=tp, fp=fp, fn=fn, tn=tn,
                precision_if_accept_all=(tp + fn) / len(pairs) if pairs else None)


def main(effort: str = "low") -> int:
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    labels = read_labels()
    rows = []
    for c in sample:
        path = VERIFY_DIR / "meta" / effort / (c["id"].replace("#", "__") + ".json")
        if c["id"] not in labels or not path.exists():
            continue
        g = json.loads(path.read_text(encoding="utf-8"))["grade"]
        rows.append(dict(audit=labels[c["id"]]["label"], coverage=c["coverage_label"],
                         accepted=g["is_defect"] if g else True))
    audited = [r for r in rows if r["audit"] != "unsure"]
    covered = [r for r in rows if r["coverage"] != "ambiguous"]
    agree = [r for r in audited if r["coverage"] != "ambiguous"]
    result = dict(
        effort=effort, labelled=len(rows), unsure=sum(r["audit"] == "unsure" for r in rows),
        vs_audited_labels=_pr([(r["audit"] == "rust", r["accepted"]) for r in audited]),
        vs_coverage_labels=_pr([(r["coverage"] == "TP", r["accepted"]) for r in covered]),
        audit_vs_coverage_agreement=(sum((r["audit"] == "rust") == (r["coverage"] == "TP") for r in agree) / len(agree))
        if agree else None,
        coverage_FP_that_audit_calls_rust=sum(r["coverage"] == "FP" and r["audit"] == "rust" for r in rows),
        coverage_FP_total=sum(r["coverage"] == "FP" for r in rows),
    )
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:2] or [])))
