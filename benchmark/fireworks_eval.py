"""Muse Glimmer 30B as the verifier on a Fireworks on-demand deployment: zero-shot baseline (and later the
Modal-tuned LoRA), on the same candidates as the other verifiers.

Sets (in this order, so the most important finish first inside the deployment window):
1. the builder's audits (100 text + 50 box candidates; precision/recall vs human labels);
2. real public negatives (185 Cloud candidates) and the Muse Image stress set (486 Cloud candidates);
3. all 5,066 text-prompt test candidates (as RESULTS 6: TP retention vs coverage labels, invalid replies, decision
   agreement with hosted Muse Spark low and with Muse Spark Open).

Deployment guards: min replicas 0, max 1, one H200, deleted in ``finally`` (``backend.clients.fireworks.deployment``),
``--max-hours`` cap (no new work after the deadline minus 5 min), and ``assert_no_deployments`` afterwards.
Cost = deployment hours x the H200 list rate ($8/h), recorded in the ledger at the end.

    .venv\\Scripts\\python.exe -m benchmark.fireworks_eval --tag zeroshot --max-hours 2
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import cv2

from backend.clients import fireworks as fw
from backend.clients.cost import CostEntry, CostLedger
from backend.perception.sam import parse_output
from backend.verify.schema import Grade
from backend.verify.verifier import Candidate, verify
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR
from benchmark.verifier_hardening import audited, negatives_cloud
from benchmark.verify_eval import VERIFY_DIR
from benchmark.verify_scale import journal_path, read_journal

H200_PER_HOUR = 8.0
RESULTS = Path(__file__).parent / "results"
LEDGER = DATA_DIR / "runs" / "cost_ledger.jsonl"
THREADS = 32


class LazyCandidate:
    """A test candidate decoded only when verified (5,066 masks would not fit in memory at once)."""

    def __init__(self, rel: str, row: dict):
        self.rel, self.row, self.candidate_id = rel, row, row["id"]

    def load(self) -> Candidate:
        obj = self.candidate_id.split("#")[1]
        insts = parse_output((SAM_DIR / "rust" / (Path(self.rel).stem + ".txt")).read_text(encoding="utf-8"), 640, 640)
        i = next(x for x in insts if x.object_id == obj)
        return Candidate(self.candidate_id, cv2.imread(str(RAW_DIR / self.rel), cv2.IMREAD_COLOR), i.mask, i.box,
                         i.confidence, source="text")


def test_candidates() -> list[tuple[dict, LazyCandidate]]:
    """All text-prompt test candidates with their coverage label (from the hosted low-effort journal)."""
    return [(r, LazyCandidate(rel, r)) for rel, rows in read_journal(journal_path("test", "low")).items() for r in rows]


def _grade_of(path: Path) -> tuple[bool, bool] | None:
    """(valid, accepted) from a cached verdict file."""
    if not path.exists():
        return None
    g = json.loads(path.read_text(encoding="utf-8"))["grade"]
    return (g is not None, Grade.model_validate(g).is_defect if g else True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="cache/result tag, e.g. zeroshot or tuned-v1")
    ap.add_argument("--model", default=fw.GLIMMER, help="model to deploy (base or uploaded LoRA model)")
    ap.add_argument("--max-hours", type=float, default=2.0)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--test-limit", type=int, default=None)
    args = ap.parse_args()
    cache = VERIFY_DIR / "fireworks" / args.tag
    cache.mkdir(parents=True, exist_ok=True)
    ledger = CostLedger(LEDGER)
    aud = audited()
    negs = {"public": negatives_cloud("public"), "muse_eval": negatives_cloud("synthetic_muse")}
    test = test_candidates()[:args.test_limit]
    jobs = [c for _, c in aud] + [c for v in negs.values() for _, c in v] + [c for _, c in test]
    print(f"{len(jobs)} candidates queued ({len(aud)} audit, {sum(map(len, negs.values()))} negatives, "
          f"{len(test)} test)", flush=True)

    created = time.time()
    ready_s = None
    stop = threading.Event()
    errors: list[str] = []
    done = [0]
    try:
        with fw.deployment(args.model, max_hours=args.max_hours) as (name, deadline):
            ready_s = time.time() - created
            print(f"deployment READY after {ready_s:.0f} s: {name}", flush=True)

            def one(c: Candidate) -> None:
                path = cache / (c.candidate_id.replace("#", "__") + ".json")
                if path.exists() or stop.is_set():
                    return
                if time.time() > deadline - 300:
                    stop.set()
                    return
                try:
                    if isinstance(c, LazyCandidate):
                        c = c.load()
                    v = verify(c, provider="fireworks", reasoning_effort=args.effort, model=name, job="fireworks-eval")
                except Exception as err:  # noqa: BLE001  stays uncached (counted as missing); auth errors stop the run
                    errors.append(f"{type(err).__name__}: {str(err)[:160]}")
                    if "BillingError" in type(err).__name__ or len(errors) > 50:
                        stop.set()
                    return
                d = asdict(v)
                d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
                path.write_text(json.dumps(d), encoding="utf-8")
                done[0] += 1
                if done[0] % 200 == 0:
                    print(f"{done[0]} verdicts, {(time.time() - created) / 60:.0f} min", flush=True)

            with ThreadPoolExecutor(max_workers=THREADS) as pool:
                list(pool.map(one, jobs))
    finally:
        hours = (time.time() - created) / 3600
        ledger.add(CostEntry(job=f"fireworks-deployment-{args.tag}", model="fireworks H200 on-demand (muse-glimmer)",
                             usd=hours * H200_PER_HOUR))
        try:
            fw.assert_no_deployments()
            left = "none"
        except RuntimeError as err:
            left = str(err)
        print(f"deployment hours {hours:.2f} (${hours * H200_PER_HOUR:.2f}); deployments left: {left}", flush=True)

    # ---- statistics -------------------------------------------------------------------------------------------
    def acc(c) -> tuple[bool, bool] | None:
        return _grade_of(cache / (c.candidate_id.replace("#", "__") + ".json"))

    from benchmark.verifier_hardening import audit_stats, neg_stats
    res = dict(tag=args.tag, model=args.model, deployment_hours=round(hours, 3), usd=round(hours * H200_PER_HOUR, 2),
               errors=len(errors), first_errors=errors[:3],
               ready_s=round(ready_s) if ready_s is not None else None)
    a = [acc(c) for _, c in aud]
    res["audited"] = audit_stats(aud, [x[1] if x else None for x in a])
    for k, v in negs.items():
        res[k] = neg_stats(v, [(acc(c) or (None, None))[1] for _, c in v])
    rows = [(r, acc(c)) for r, c in test]
    rows = [(r, x) for r, x in rows if x]
    tps = [x[1] for r, x in rows if r["label"] == "TP"]
    agree_low, agree_open = [], []
    for r, x in rows:
        n = r["id"].replace("#", "__") + ".json"
        low = _grade_of(VERIFY_DIR / "meta" / "low" / n)
        op = _grade_of(VERIFY_DIR / "baseten" / "low-retry8000" / n) or _grade_of(VERIFY_DIR / "baseten" / "low" / n)
        if low and low[0] and x[0]:
            agree_low.append(low[1] == x[1])
        if op and op[0] and x[0]:
            agree_open.append(op[1] == x[1])
    res["test"] = dict(candidates=len(rows), of=len(test), invalid_reply_rate=(sum(not x[0] for _, x in rows) / len(rows)) if rows else None,
                       tp_retention=sum(tps) / len(tps) if tps else None, accepted_share=(sum(x[1] for _, x in rows) / len(rows)) if rows else None,
                       agreement_with_hosted_low=sum(agree_low) / len(agree_low) if agree_low else None,
                       agreement_with_muse_spark_open=sum(agree_open) / len(agree_open) if agree_open else None)
    lat = [json.loads((cache / f).read_text(encoding="utf-8"))["latency_s"] for f in
           [c.candidate_id.replace("#", "__") + ".json" for c in jobs] if (cache / f).exists()]
    res["latency_s_median"] = sorted(lat)[len(lat) // 2] if lat else None
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"fireworks_glimmer_{args.tag}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
