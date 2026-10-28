"""Score Glimmer verifier replies (``modal_apps/glimmer.py::evaluate``) against the same labels as the other verifiers.

Reads the evaluation file (``benchmark.glimmer_data --eval``) for labels and the replies downloaded from the Modal
volume (``/results/eval_<tag>.jsonl``). Unparseable replies count as accept (fail open), as everywhere else.

    .venv\\Scripts\\python.exe -m benchmark.glimmer_eval_score zeroshot tuned-v1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from benchmark.audit_eval import wilson
from benchmark.download_dataset import DATA_DIR
from benchmark.fireworks_eval import _grade_of
from benchmark.verify_eval import VERIFY_DIR

EVAL = DATA_DIR / "glimmer" / "data" / "eval.jsonl"
RES = DATA_DIR / "glimmer" / "results"
OUT = Path(__file__).parent / "results"


def meta() -> dict[tuple[str, str], dict]:
    out = {}
    with EVAL.open(encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            e.pop("messages")
            out[(e["set"], e["id"])] = e  # a few audit candidates are also in the test sample
    return out


def score(tag: str, m: dict[tuple[str, str], dict]) -> dict:
    rows = [json.loads(l) for l in (RES / f"eval_{tag}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r | m[(r["set"], r["id"])] for r in rows if (r["set"], r["id"]) in m]
    acc = lambda r: True if r["accept"] is None else r["accept"]  # noqa: E731
    out = dict(tag=tag, replies=len(rows), of=len(m), unparsed=sum(r["accept"] is None for r in rows))
    a = [r for r in rows if r["set"] == "audit"]
    tp = sum(r["human_rust"] and acc(r) for r in a)
    fn = sum(r["human_rust"] and not acc(r) for r in a)
    fp = sum(acc(r) and not r["human_rust"] for r in a)
    tn = sum(not r["human_rust"] and not acc(r) for r in a)
    out["audit"] = dict(n=len(a), recall=tp / (tp + fn) if tp + fn else None, recall_ci=wilson(tp, tp + fn),
                        precision=tp / (tp + fp) if tp + fp else None, not_rust_rejected=f"{tn} / {tn + fp}")
    for s in ("public", "muse_eval"):
        rs = [r for r in rows if r["set"] == s]
        imgs = {r["image"] for r in rs}
        bad = {r["image"] for r in rs if acc(r)}
        out[s] = dict(candidates=len(rs), accepted=sum(acc(r) for r in rs), images=len(imgs),
                      images_with_alarm=len(bad))
    t = [r for r in rows if r["set"] == "test"]
    tps = [acc(r) for r in t if r["coverage_label"] == "TP"]
    agree = {"low": [], "open": []}
    for r in t:
        n = r["id"].replace("#", "__") + ".json"
        low = _grade_of(VERIFY_DIR / "meta" / "low" / n)
        op = _grade_of(VERIFY_DIR / "baseten" / "low-retry8000" / n) or _grade_of(VERIFY_DIR / "baseten" / "low" / n)
        if low and low[0] and r["accept"] is not None:
            agree["low"].append(low[1] == r["accept"])
        if op and op[0] and r["accept"] is not None:
            agree["open"].append(op[1] == r["accept"])
    out["test"] = dict(n=len(t), tp_retention=sum(tps) / len(tps) if tps else None,
                       agreement_with_hosted_low=sum(agree["low"]) / len(agree["low"]) if agree["low"] else None,
                       agreement_with_muse_spark_open=sum(agree["open"]) / len(agree["open"]) if agree["open"] else None)
    return out


def main() -> int:
    m = meta()
    res = {tag: score(tag, m) for tag in sys.argv[1:]}
    OUT.mkdir(exist_ok=True)
    (OUT / "glimmer_eval.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
