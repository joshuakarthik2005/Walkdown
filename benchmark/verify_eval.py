"""Evaluate the Muse Spark verifier on SAM candidates.

Candidates are SAM 3.1 "rust" instances (from the SAM cache). Each gets a
ground-truth label from its overlap with the annotated masks
(see DECISIONS.md, "Verifier ground truth"):
    coverage = |candidate mask ∩ union of GT masks| / |candidate mask|
    TP if coverage >= 0.5, FP if coverage < 0.1, otherwise "ambiguous"
    (ambiguous candidates are verified and reported, but excluded from the
    classifier metrics).

Reports the verifier as a classifier (precision/recall of is_defect against
the label, FPs removed, TPs wrongly rejected), candidate-level precision of
SAM alone vs SAM + verifier, invalid replies, consistency flags, real cost and
latency per candidate, and a projection for the full test split. Severity has
no ground truth; ``--repeat N`` grades N candidates a second time to measure
agreement instead.

Verdicts are cached under WALKDOWN_DATA_DIR/runs/verify/<provider>/.

    .venv\\Scripts\\python.exe -m benchmark.verify_eval dev --provider meta --n 50 --repeat 30 --max-usd 1
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from backend.clients.cost import CostLedger
from backend.perception.sam import parse_output
from backend.verify.verifier import Candidate, Verdict, verify
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR, ground_truth
from benchmark.splits import SEED, load_split

VERIFY_DIR = DATA_DIR / "runs" / "verify"
RESULTS_DIR = Path(__file__).parent / "results"
TP_COVERAGE, FP_COVERAGE = 0.5, 0.1


def label(mask: np.ndarray, gt_union: np.ndarray) -> tuple[str, float]:
    """TP / FP / ambiguous from the share of the candidate inside annotated corrosion."""
    coverage = float((mask & gt_union).sum() / max(1, mask.sum()))
    return ("TP" if coverage >= TP_COVERAGE else "FP" if coverage < FP_COVERAGE else "ambiguous"), coverage


def load_candidates(split: str) -> list[dict]:
    """Every cached SAM 'rust' instance on the split, with its label."""
    images = load_split(split)
    gt = ground_truth(images)
    out = []
    for rel in images:
        path = SAM_DIR / "rust" / (Path(rel).stem + ".txt")
        if not path.exists():
            continue
        union = np.logical_or.reduce(gt[rel]) if gt[rel] else np.zeros((640, 640), bool)
        for inst in parse_output(path.read_text(encoding="utf-8"), 640, 640):
            lab, cov = label(inst.mask, union)
            out.append(dict(id=f"{Path(rel).stem}#{inst.object_id}", image=rel, instance=inst, label=lab,
                            coverage=cov))
    return out


def _cached_verify(cand: dict, provider: str, effort: str, ledger: CostLedger, suffix: str = "") -> Verdict:
    cache = VERIFY_DIR / provider / f"{effort}{suffix}"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (cand["id"].replace("#", "__") + ".json")
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        from backend.verify.schema import Grade
        d["grade"] = Grade.model_validate(d["grade"]) if d["grade"] else None
        return Verdict(**d)
    image = cv2.imread(str(RAW_DIR / cand["image"]), cv2.IMREAD_COLOR)
    inst = cand["instance"]
    v = verify(Candidate(cand["id"], image, inst.mask, inst.box, inst.confidence), provider=provider,
               reasoning_effort=effort, ledger=ledger, job=f"verify-{provider}")
    d = asdict(v)
    d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
    path.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return v


def classifier_metrics(cands: list[dict], verdicts: dict[str, Verdict]) -> dict:
    """Verifier vs ground-truth label, ambiguous excluded; invalid replies count as 'accept' (fail open)."""
    tp = fp = fn = tn = 0
    for c in cands:
        if c["label"] == "ambiguous":
            continue
        v = verdicts[c["id"]]
        accepted = v.grade.is_defect if v.grade else True
        if c["label"] == "TP":
            tp, fn = tp + accepted, fn + (not accepted)
        else:
            fp, tn = fp + accepted, tn + (not accepted)
    n_tp, n_fp = tp + fn, fp + tn
    return dict(
        labelled_tp=n_tp, labelled_fp=n_fp,
        verifier_precision=tp / (tp + fp) if tp + fp else 0.0,
        verifier_recall=tp / n_tp if n_tp else 0.0,
        fps_removed=tn, fps_removed_share=tn / n_fp if n_fp else 0.0,
        tps_wrongly_rejected=fn, tps_wrongly_rejected_share=fn / n_tp if n_tp else 0.0,
        candidate_precision_sam_alone=n_tp / (n_tp + n_fp) if n_tp + n_fp else 0.0,
        candidate_precision_sam_plus_verifier=tp / (tp + fp) if tp + fp else 0.0,
        candidate_recall_sam_plus_verifier_vs_sam=tp / n_tp if n_tp else 0.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--provider", default="meta", choices=["meta", "baseten"])
    ap.add_argument("--effort", default="low")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--repeat", type=int, default=0)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    all_cands = load_candidates(args.split)
    rng = random.Random(SEED)
    sample = rng.sample(all_cands, min(args.n, len(all_cands)))
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    print(f"{len(all_cands)} candidates on {args.split}; verifying {len(sample)} with {args.provider} ({args.effort})")

    def run(cs: list[dict], suffix: str = "") -> dict[str, Verdict]:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            vs = list(pool.map(lambda c: _cached_verify(c, args.provider, args.effort, ledger, suffix), cs))
        if args.provider == "meta" and ledger.total() > args.max_usd:
            raise SystemExit(f"spent ${ledger.total():.3f}, over the ${args.max_usd} limit")
        return {v.candidate_id: v for v in vs}

    first = run(sample[:5])  # small probe before the rest, so a format problem costs little
    if any(v.grade is None for v in first.values()):
        print("probe replies:", [(v.candidate_id, v.error, v.raw[:200]) for v in first.values()])
    verdicts = first | run(sample[5:])
    vs = list(verdicts.values())
    valid = [v for v in vs if v.grade]
    result = dict(
        split=args.split, provider=args.provider, effort=args.effort, candidates_available=len(all_cands),
        label_counts={k: sum(c["label"] == k for c in all_cands) for k in ("TP", "FP", "ambiguous")},
        sample_label_counts={k: sum(c["label"] == k for c in sample) for k in ("TP", "FP", "ambiguous")},
        verified=len(vs), invalid_replies=len(vs) - len(valid),
        metrics=classifier_metrics(sample, verdicts),
        flags={f: sum(f in v.flags for v in vs) for f in sorted({f for v in vs for f in v.flags})},
        severity_histogram={s: sum(v.grade.severity == s for v in valid if v.grade.is_defect) for s in range(1, 6)},
        cost=dict(
            usd_total=sum(v.usd or 0 for v in vs) if args.provider == "meta" else None,
            usd_per_candidate=statistics.mean(v.usd or 0 for v in vs) if args.provider == "meta" else None,
            input_tokens_mean=statistics.mean(v.input_tokens for v in vs),
            cached_tokens_mean=statistics.mean(v.cached_tokens for v in vs),
            output_tokens_mean=statistics.mean(v.output_tokens for v in vs),
            reasoning_tokens_mean=statistics.mean(v.reasoning_tokens for v in vs),
            output_tokens_max=max(v.output_tokens for v in vs),
            latency_s_median=statistics.median(v.latency_s for v in vs),
            latency_s_p90=sorted(v.latency_s for v in vs)[int(0.9 * (len(vs) - 1))],
        ),
    )
    if args.provider == "meta":
        per_image = len(all_cands) / len(load_split(args.split))
        test_cands = per_image * len(load_split("test"))
        result["projection"] = dict(candidates_per_image=per_image, test_candidates_estimated=round(test_cands),
                                    usd_for_test=test_cands * result["cost"]["usd_per_candidate"])
    if args.repeat:
        again = run(sample[: args.repeat], suffix="_repeat")
        pairs = [(verdicts[k].grade, again[k].grade) for k in again if verdicts[k].grade and again[k].grade]
        both = [(a, b) for a, b in pairs if a.is_defect and b.is_defect]
        result["consistency"] = dict(
            pairs=len(pairs),
            is_defect_agreement=sum(a.is_defect == b.is_defect for a, b in pairs) / len(pairs) if pairs else None,
            severity_pairs_both_defect=len(both),
            severity_exact=sum(a.severity == b.severity for a, b in both) / len(both) if both else None,
            severity_within_1=sum(abs(a.severity - b.severity) <= 1 for a, b in both) / len(both) if both else None,
            defect_type_agreement=sum(a.defect_type == b.defect_type for a, b in pairs) / len(pairs) if pairs else None,
        )
    result["usd_spent_this_run"] = ledger.total() if args.provider == "meta" else None
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"verify_{args.split}_{args.provider}_{args.effort}_n{len(sample)}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
