"""Verifier hardening: does the v2 prompt (look-alike checklist + texture evidence) cut false alarms without
costing real-rust recall?

Protocol (builder rules, 2026-10-28):
- **Tune** only on FLUX-tune candidates (synthetic, training/tuning split; ``benchmark.synthetic_candidates``).
- **Evaluate** on sets never used for tuning:
  - Muse Image stress set: the Cloud text+boxes candidates of ``negatives_fp synthetic_muse``;
  - real public negatives: the Cloud text+boxes candidates of ``negatives_fp public``;
  - the builder's audited labels: 100 text-prompt + 50 box-only test candidates (unsure excluded).
- **Accept** v2 only if false alarms drop on the negatives AND audited real-rust recall drops by no more than
  3 points (both audits combined, sample counts), for the verifier the agent uses (hosted Muse Spark, minimal).
Muse Spark Open (On-prem verifier) is evaluated too on the real negatives and the audits, within the Baseten cap.

Verdicts are cached under WALKDOWN_DATA_DIR/runs/hardening/<prompt>/<provider>-<effort>/.

    .venv\\Scripts\\python.exe -m benchmark.verifier_hardening tune --max-usd 1
    .venv\\Scripts\\python.exe -m benchmark.verifier_hardening eval --max-usd 10
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import cv2

from backend.clients.cost import CostLedger
from backend.perception.boxes import merge_with_text, parse_box_output
from backend.perception.sam import parse_output
from backend.perception.sam_open import to_instances
from backend.verify.schema import Grade
from backend.verify.verifier import Candidate, verify
from benchmark.audit_eval import wilson
from benchmark.download_dataset import DATA_DIR, RAW_DIR

CACHE = DATA_DIR / "runs" / "hardening"
LEDGER = DATA_DIR / "runs" / "cost_ledger.jsonl"
RESULTS = Path(__file__).parent / "results"
FP_CACHE = DATA_DIR / "runs" / "negatives_fp"
FLUX_DIR = DATA_DIR / "synthetic" / "flux_train"
FLUX_SAM = DATA_DIR / "runs" / "sam_open" / "flux_train"
THREADS = 8


# ---- candidate sets ---------------------------------------------------------------------------------------------

def flux_tune() -> list[tuple[str, Candidate]]:
    """FLUX-tune candidates: SAM 3.1 open-weights masks of the look-alike object, largest per image; all not-rust.
    Marked as box-proposed: in production, look-alikes like these mostly arrive through box proposals."""
    out = []
    for line in (FLUX_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        m = json.loads(line)
        sam = FLUX_SAM / (Path(m["file"]).stem + ".json")
        if m.get("subset") != "tune" or not sam.exists():
            continue
        img = cv2.imread(str(FLUX_DIR / m["file"]), cv2.IMREAD_COLOR)
        insts = to_instances(json.loads(sam.read_text(encoding="utf-8")), frame=0)
        if insts:  # one candidate per image (largest), to keep the tuning set small and varied
            inst = max(insts, key=lambda i: i.area)
            cid = f"{Path(m['file']).stem}#{inst.object_id}"
            out.append((cid, Candidate(cid, img, inst.mask, inst.box, inst.confidence, source="box")))
    return out


def negatives_cloud(set_name: str) -> list[tuple[str, Candidate]]:
    """Cloud text+boxes candidates of a negatives set (as scored by benchmark.negatives_fp), image-tagged."""
    folder = {"public": DATA_DIR / "negatives_public" / "images", "synthetic_muse": DATA_DIR / "synthetic" / "muse_eval"}[set_name]
    cache = FP_CACHE / set_name / "cloud"
    out = []
    for tpath in sorted((cache / "text").glob("*.txt")):
        p = folder / f"{tpath.stem}.jpg"
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        text = parse_output(tpath.read_text(encoding="utf-8"), w, h)
        bpath = cache / "box_masks" / f"{tpath.stem}.txt"
        box = parse_box_output(bpath.read_text(encoding="utf-8"), w, h) if bpath.exists() else []
        for obj, inst in merge_with_text(text, box):
            cid = f"{tpath.stem}#{obj}"
            out.append((tpath.stem, Candidate(cid, img, inst.mask, inst.box, inst.confidence,
                                              source="box" if obj.startswith("b") else "text")))
    return out


def audited() -> list[tuple[bool, Candidate]]:
    """(human says rust, candidate) for both audits; unsure excluded."""
    from benchmark.box_verify import candidates as box_candidates
    from benchmark.label_app import BOX_LABELS_PATH, BOX_SAMPLE_PATH, LABEL_DIR, read_labels
    from benchmark.sam_dryrun import RUN_DIR as SAM_DIR
    out = []
    t_labels = read_labels(LABEL_DIR / "audit.jsonl")
    for c in json.loads((LABEL_DIR / "audit_sample.json").read_text(encoding="utf-8")):
        lab = t_labels.get(c["id"], {}).get("label")
        if lab not in ("rust", "not_rust"):
            continue
        insts = parse_output((SAM_DIR / "rust" / (Path(c["image"]).stem + ".txt")).read_text(encoding="utf-8"), 640, 640)
        inst = next(i for i in insts if i.object_id == c["object_id"])
        img = cv2.imread(str(RAW_DIR / c["image"]), cv2.IMREAD_COLOR)
        out.append((lab == "rust", Candidate(c["id"], img, inst.mask, inst.box, inst.confidence, source="text")))
    b_labels = read_labels(BOX_LABELS_PATH)
    for c in json.loads(BOX_SAMPLE_PATH.read_text(encoding="utf-8")):
        lab = b_labels.get(c["id"], {}).get("label")
        if lab not in ("rust", "not_rust"):
            continue
        _, merged, records = box_candidates(c["image"])
        inst = next(i for i, r in zip(merged, records) if r["id"] == c["id"])
        img = cv2.imread(str(RAW_DIR / c["image"]), cv2.IMREAD_COLOR)
        out.append((lab == "rust", Candidate(c["id"], img, inst.mask, inst.box, inst.confidence, source="box")))
    return out


# ---- verdicts ---------------------------------------------------------------------------------------------------

def accepted(c: Candidate, prompt: str, provider: str, effort: str, ledger: CostLedger, cap: float) -> bool | None:
    """Accept? (cached; invalid replies fail open; None when the spend cap stops new calls)."""
    path = CACHE / prompt / f"{provider}-{effort}" / (c.candidate_id.replace("#", "__") + ".json")
    if not path.exists():
        if ledger.total() > cap:
            return None
        v = verify(c, provider=provider, reasoning_effort=effort, ledger=ledger, job=f"hardening-{prompt}",
                   prompt_version=prompt)
        d = asdict(v)
        d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d), encoding="utf-8")
    g = json.loads(path.read_text(encoding="utf-8"))["grade"]
    return Grade.model_validate(g).is_defect if g else True


def judge(items: list, prompt: str, provider: str, effort: str, ledger: CostLedger, cap: float) -> list:
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        return list(pool.map(lambda it: accepted(it[1], prompt, provider, effort, ledger, cap), items))


def neg_stats(items: list[tuple[str, Candidate]], acc: list) -> dict:
    """False alarms on a negatives set: accepted candidates, and images with at least one accepted candidate."""
    done = [(img, a) for (img, _), a in zip(items, acc) if a is not None]
    imgs = sorted({img for img, _ in done})
    bad = {img for img, a in done if a}
    return dict(candidates=len(done), accepted=sum(a for _, a in done), images=len(imgs), images_with_alarm=len(bad),
                image_alarm_rate=len(bad) / len(imgs) if imgs else None, ci=wilson(len(bad), len(imgs)) if imgs else None,
                complete=len(done) == len(items))


def audit_stats(items: list[tuple[bool, Candidate]], acc: list) -> dict:
    done = [(r, a) for (r, _), a in zip(items, acc) if a is not None]
    tp = sum(r and a for r, a in done)
    fn = sum(r and not a for r, a in done)
    fp = sum(a and not r for r, a in done)
    tn = sum(not r and not a for r, a in done)
    return dict(n=len(done), recall=tp / (tp + fn) if tp + fn else None, recall_ci=wilson(tp, tp + fn),
                not_rust_rejected=tn / (tn + fp) if tn + fp else None, tp=tp, fn=fn, fp=fp, tn=tn,
                complete=len(done) == len(items))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("tune", "eval"))
    ap.add_argument("--prompts", default="v1,v2")
    ap.add_argument("--max-usd", type=float, required=True, help="cap on new spend in this run")
    ap.add_argument("--open", action="store_true", help="also evaluate Muse Spark Open (Baseten) on real data")
    args = ap.parse_args()
    ledger = CostLedger(LEDGER)
    prompts = args.prompts.split(",")
    out: dict = dict(stage=args.stage)
    if args.stage == "tune":
        items = flux_tune()
        for p in prompts:
            out[p] = neg_stats([(cid.split("#")[0], c) for cid, c in items],
                               judge(items, p, "meta", "minimal", ledger, args.max_usd))
    else:
        sets = {"muse_eval": negatives_cloud("synthetic_muse"), "public": negatives_cloud("public")}
        aud = audited()
        verifiers = [("meta", "minimal")] + ([("baseten", "low")] if args.open else [])
        for provider, effort in verifiers:
            key = f"{provider}-{effort}"
            for p in prompts:
                r = out.setdefault(key, {}).setdefault(p, {})
                for name, items in sets.items():
                    if provider == "baseten" and name == "muse_eval":
                        continue  # Baseten cap: real data first
                    r[name] = neg_stats(items, judge(items, p, provider, effort, ledger, args.max_usd))
                r["audited"] = audit_stats(aud, judge(aud, p, provider, effort, ledger, args.max_usd))
    out["usd"] = round(ledger.total(), 4)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"verifier_hardening_{args.stage}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
