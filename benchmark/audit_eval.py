"""Human-audited evaluation (n = 100): every verifier, and the dataset's coverage labels, against the builder's labels.

The audit sample (``benchmark.label_app``) is 100 SAM 3.1 text-prompt candidates from the test split, stratified by
the dataset coverage label: 40 "TP", 40 "FP", 20 "ambiguous". The builder labelled each crop rust / not rust /
unsure without seeing the dataset label or any verdict. "unsure" is excluded from every metric and counted
separately.

Because the sample is stratified, raw sample rates over-represent FP and ambiguous candidates. Every headline
metric is therefore reported twice: on the sample as labelled, and **reweighted** to the test split's candidate mix
(3,616 TP / 1,325 FP / 125 ambiguous of 5,066; stratum weights = population share / sample share). 95% intervals:
Wilson for sample proportions; for reweighted figures, a stratified bootstrap (2,000 resamples within strata, seeded).

Verifiers (cached verdicts; the minimal-effort ones are filled by this script if missing):
- hosted Muse Spark ``muse-spark-1.3`` at low and minimal effort;
- Muse Spark Open on Baseten (low effort, 4,000 tokens; the 8,000-token retry verdict where the first reply was invalid);
- Muse Wonder senior review on the candidates the low-effort first pass escalates: Wonder's own verdict, and the
  product decision after the fail-safe rule (a defect Wonder rejects stays, flagged for human review).
Invalid replies count as "accept" (fail open), as in the product.

    .venv\\Scripts\\python.exe -m benchmark.audit_eval --max-usd 0.5
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from backend.clients.cost import CostLedger
from backend.verify.escalation import escalation_reason
from backend.verify.schema import Grade
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.label_app import SAMPLE_PATH, read_labels
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR
from benchmark.verify_eval import VERIFY_DIR, _cached_verify

OUT = Path(__file__).parent / "results" / "audit_eval.json"
POPULATION = {"TP": 3616, "FP": 1325, "ambiguous": 125}  # test-split candidates (results/verify_scale_test_meta_low.json)
SEED = 20261028
BOOT = 2000


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def _grade(path: Path) -> tuple[bool, Grade | None] | None:
    if not path.exists():
        return None
    g = json.loads(path.read_text(encoding="utf-8"))["grade"]
    g = Grade.model_validate(g) if g else None
    return (g.is_defect if g else True), g


def _metrics(rows: list[dict], key: str, weights: dict[str, float]) -> dict:
    """Precision, recall, accuracy of ``row[key]`` (accept) vs human rust, raw and reweighted, with 95% CIs."""
    rows = [r for r in rows if r.get(key) is not None]

    def stats(rs: list[dict], w: dict[str, float]) -> dict[str, float | None]:
        tp = sum(w[r["stratum"]] for r in rs if r["rust"] and r[key])
        fp = sum(w[r["stratum"]] for r in rs if not r["rust"] and r[key])
        fn = sum(w[r["stratum"]] for r in rs if r["rust"] and not r[key])
        tn = sum(w[r["stratum"]] for r in rs if not r["rust"] and not r[key])
        tot = tp + fp + fn + tn
        return dict(precision=tp / (tp + fp) if tp + fp else None, recall=tp / (tp + fn) if tp + fn else None,
                    accuracy=(tp + tn) / tot if tot else None,
                    not_rust_rejected=tn / (tn + fp) if tn + fp else None)

    ones = {k: 1.0 for k in weights}
    raw = stats(rows, ones)
    tp = sum(r["rust"] and r[key] for r in rows)
    fp = sum(not r["rust"] and r[key] for r in rows)
    fn = sum(r["rust"] and not r[key] for r in rows)
    tn = len(rows) - tp - fp - fn
    out = dict(n=len(rows), tp=tp, fp=fp, fn=fn, tn=tn,
               sample=dict(precision=raw["precision"], precision_ci=wilson(tp, tp + fp),
                           recall=raw["recall"], recall_ci=wilson(tp, tp + fn),
                           accuracy=raw["accuracy"], accuracy_ci=wilson(tp + tn, len(rows)),
                           not_rust_rejected=raw["not_rust_rejected"], not_rust_rejected_ci=wilson(tn, tn + fp)))
    est = stats(rows, weights)
    rng = random.Random(SEED)
    by = {s: [r for r in rows if r["stratum"] == s] for s in weights}
    boots: dict[str, list[float]] = {k: [] for k in est}
    for _ in range(BOOT):
        rs = [rng.choice(v) for v in by.values() if v for _ in v]
        for k, v in stats(rs, weights).items():
            if v is not None:
                boots[k].append(v)
    out["reweighted"] = {k: v for k, v in est.items()}
    out["reweighted_ci"] = {k: ([round(float(np.percentile(b, 2.5)), 3), round(float(np.percentile(b, 97.5)), 3)]
                                if b else None) for k, b in boots.items()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-usd", type=float, default=0.5, help="cap for filling missing minimal-effort verdicts")
    args = ap.parse_args()
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    labels = read_labels()
    sample = [c for c in sample if c["id"] in labels]

    # Fill missing hosted minimal-effort verdicts (same masks as the cached low-effort ones).
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    from backend.perception.sam import parse_output
    todo = [c for c in sample if not (VERIFY_DIR / "meta" / "minimal" / (c["id"].replace("#", "__") + ".json")).exists()]

    def fill(c: dict) -> None:
        if ledger.total() > args.max_usd:
            return
        insts = parse_output((SAM_DIR / "rust" / (Path(c["image"]).stem + ".txt")).read_text(encoding="utf-8"), 640, 640)
        inst = next(i for i in insts if i.object_id == c["object_id"])
        _cached_verify(dict(id=c["id"], image=c["image"], instance=inst), "meta", "minimal", ledger)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fill, todo))
    assert RAW_DIR.exists()

    rows = []
    for c in sample:
        name = c["id"].replace("#", "__") + ".json"
        low = _grade(VERIFY_DIR / "meta" / "low" / name)
        mini = _grade(VERIFY_DIR / "meta" / "minimal" / name)
        open_ = _grade(VERIFY_DIR / "baseten" / "low" / name)
        if open_ and open_[1] is None:  # invalid at 4,000 tokens: the 8,000-token retry verdict, as in RESULTS 6
            open_ = _grade(VERIFY_DIR / "baseten" / "low-retry8000" / name) or open_
        r = dict(id=c["id"], stratum=c["coverage_label"], human=labels[c["id"]]["label"],
                 low=low[0] if low else None, minimal=mini[0] if mini else None,
                 open=open_[0] if open_ else None, escalated=bool(low and escalation_reason(low[1])))
        wonder = _grade(VERIFY_DIR / "wonder" / "low" / name) if r["escalated"] else None
        r["wonder"] = wonder[0] if wonder else (r["low"] if not r["escalated"] else None)  # not escalated: first pass
        # Product decision with the fail-safe rule: Wonder can add a rejected defect back, never drop an accepted one.
        r["senior_product"] = (r["low"] or bool(wonder and wonder[0])) if r["low"] is not None else None
        r["wonder_overturned"] = bool(wonder and wonder[0] != r["low"])
        rows.append(r)

    counts = {s: sum(c["coverage_label"] == s for c in sample) for s in POPULATION}
    unsure = [r for r in rows if r["human"] == "unsure"]
    sure = [r for r in rows if r["human"] != "unsure"]
    for r in sure:
        r["rust"] = r["human"] == "rust"
    n_sure = {s: sum(r["stratum"] == s for r in sure) for s in POPULATION}
    total = sum(POPULATION.values())
    weights = {s: (POPULATION[s] / total) / (n_sure[s] / len(sure)) if n_sure[s] else 0.0 for s in POPULATION}

    def share(rs: list[dict]) -> dict:
        k = sum(r["rust"] for r in rs)
        return dict(n=len(rs), rust=k, share=k / len(rs) if rs else None, ci=wilson(k, len(rs)))

    overturned = [r for r in sure if r["wonder_overturned"]]
    result = dict(
        labelled=len(rows), unsure=len(unsure), unsure_by_stratum={s: sum(r["stratum"] == s for r in unsure)
                                                                   for s in POPULATION},
        sample_by_stratum=counts, used_by_stratum=n_sure, reweighting=dict(population=POPULATION, weights=weights),
        human_rust_share_text_candidates=dict(
            sample=share(sure),
            reweighted=sum(weights[r["stratum"]] for r in sure if r["rust"]) / sum(weights[r["stratum"]] for r in sure),
            by_stratum={s: share([r for r in sure if r["stratum"] == s]) for s in POPULATION}),
        dataset_label_vs_human=dict(
            confusion={s: {h: sum(r["stratum"] == s and r["human"] == h for r in rows)
                           for h in ("rust", "not_rust", "unsure")} for s in POPULATION},
            dataset_FP_human_rust=share([r for r in sure if r["stratum"] == "FP"]),
            dataset_TP_human_not_rust=dict(n=n_sure["TP"], k=sum(not r["rust"] for r in sure if r["stratum"] == "TP"),
                                           ci=wilson(sum(not r["rust"] for r in sure if r["stratum"] == "TP"),
                                                     n_sure["TP"])),
            agreement_on_TP_FP=share([dict(rust=(r["stratum"] == "TP") == r["rust"]) for r in sure
                                      if r["stratum"] != "ambiguous"])),
        verifiers={k: _metrics(sure, k, weights) for k in ("low", "minimal", "open", "senior_product")},
        senior=dict(escalated=sum(r["escalated"] for r in sure),
                    wonder_reviewed=sum(r["escalated"] and r["wonder"] is not None for r in sure),
                    wonder_own_verdict_on_escalated=_metrics([r for r in sure if r["escalated"]], "wonder", weights),
                    first_pass_on_escalated=_metrics([r for r in sure if r["escalated"]], "low", weights),
                    overturned=[dict(id=r["id"], stratum=r["stratum"], human=r["human"], first_pass_accept=r["low"],
                                     wonder_accept=r["wonder"]) for r in overturned],
                    overturned_matching_human=sum(r["wonder"] == r["rust"] for r in overturned)),
        usd_minimal_fill=ledger.total(),
    )
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
