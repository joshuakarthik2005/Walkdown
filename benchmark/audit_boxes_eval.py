"""Human audit of box-only candidates (n = 50), and the combined audited figures with the text-prompt audit.

Box-only candidates are the merged text + boxes candidates on the test split that are new (not a reused text-prompt
candidate; ids ``<stem>#tb<k>``, ``benchmark.box_verify``). The sample is stratified by dataset coverage label
(20 TP / 20 FP / 10 ambiguous; ``benchmark.label_app --set boxes``). "unsure" is excluded and counted.

Verdicts: hosted Muse Spark low (cached by box_verify) and minimal, Muse Spark Open (Baseten, product setting
max_tokens 8,000); missing ones are filled here. Invalid replies count as accept (fail open).

Reweighting: box sample to the 5,385 new box candidates (2,859 TP / 1,852 FP / 674 ambiguous); the combined
figure uses six strata (source x coverage label) with the text-prompt population (3,616 / 1,325 / 125), i.e. the
default pipeline's candidates approximated as all text candidates plus all new box candidates.

    .venv\\Scripts\\python.exe -m benchmark.audit_boxes_eval --max-usd 1
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.clients.cost import CostLedger
from benchmark.audit_eval import POPULATION as TEXT_POP
from benchmark.audit_eval import SAMPLE_PATH as TEXT_SAMPLE
from benchmark.audit_eval import _grade, _metrics, wilson
from benchmark.download_dataset import DATA_DIR
from benchmark.label_app import BOX_LABELS_PATH, BOX_SAMPLE_PATH, read_labels
from benchmark.label_app import LABEL_DIR
from benchmark.verify_eval import VERIFY_DIR, _cached_verify

OUT = Path(__file__).parent / "results" / "audit_boxes_eval.json"
BOX_POP = {"TP": 2859, "FP": 1852, "ambiguous": 674}  # results/box_verify_test.json, new candidates
OPEN_SUFFIX = "-8000"  # Muse Spark Open verdicts for box candidates at the product setting (max_tokens 8,000)


def newcombe(k1: int, n1: int, k2: int, n2: int) -> list[float]:
    """95% interval for p1 - p2 (Newcombe hybrid score, from Wilson intervals)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    return [round(d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), 3), round(d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2), 3)]


def _rows(sample: list[dict], labels: dict, open_dir: str) -> list[dict]:
    rows = []
    for c in sample:
        n = c["id"].replace("#", "__") + ".json"
        low, mini, op = (_grade(VERIFY_DIR / d / n) for d in ("meta/low", "meta/minimal", open_dir))
        if open_dir == "baseten/low" and op and op[1] is None:
            op = _grade(VERIFY_DIR / "baseten" / "low-retry8000" / n) or op
        rows.append(dict(id=c["id"], stratum=c["coverage_label"], human=labels[c["id"]]["label"],
                         low=low[0] if low else None, minimal=mini[0] if mini else None, open=op[0] if op else None))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-usd", type=float, default=1.0)
    args = ap.parse_args()
    sample = json.loads(BOX_SAMPLE_PATH.read_text(encoding="utf-8"))
    labels = read_labels(BOX_LABELS_PATH)
    sample = [c for c in sample if c["id"] in labels]

    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    from benchmark.box_verify import candidates

    def fill(c: dict) -> None:
        n = c["id"].replace("#", "__") + ".json"
        need = [(p, e, s) for p, e, s in (("meta", "minimal", ""), ("baseten", "low", OPEN_SUFFIX))
                if not (VERIFY_DIR / p / f"{e}{s}" / n).exists()]
        if not need or ledger.total() > args.max_usd:
            return
        _, merged, records = candidates(c["image"])
        inst = next(i for i, r in zip(merged, records) if r["id"] == c["id"])
        for p, e, s in need:
            _cached_verify(dict(id=c["id"], image=c["image"], instance=inst), p, e, ledger, suffix=s,
                           max_tokens=8000 if p == "baseten" else None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fill, sample))

    rows = _rows(sample, labels, f"baseten/low{OPEN_SUFFIX}")
    sure = [r | {"rust": r["human"] == "rust"} for r in rows if r["human"] != "unsure"]
    n_sure = {s: sum(r["stratum"] == s for r in sure) for s in BOX_POP}
    tot = sum(BOX_POP.values())
    w_box = {s: (BOX_POP[s] / tot) / (n_sure[s] / len(sure)) if n_sure[s] else 0.0 for s in BOX_POP}

    # The first audit (text-prompt candidates), for the comparison and the combined figure.
    t_sample = json.loads(TEXT_SAMPLE.read_text(encoding="utf-8"))
    t_labels = read_labels(LABEL_DIR / "audit.jsonl")
    t_rows = _rows([c for c in t_sample if c["id"] in t_labels], t_labels, "baseten/low")
    t_sure = [r | {"rust": r["human"] == "rust"} for r in t_rows if r["human"] != "unsure"]

    def share(rs: list[dict]) -> dict:
        k = sum(r["rust"] for r in rs)
        return dict(n=len(rs), rust=k, share=k / len(rs) if rs else None, ci=wilson(k, len(rs)))

    # Combined: six strata (source x label), weights = population share / sample share.
    combo = [r | {"stratum": f"text/{r['stratum']}"} for r in t_sure] + [r | {"stratum": f"box/{r['stratum']}"}
                                                                          for r in sure]
    pop6 = {f"text/{k}": v for k, v in TEXT_POP.items()} | {f"box/{k}": v for k, v in BOX_POP.items()}
    n6 = {s: sum(r["stratum"] == s for r in combo) for s in pop6}
    w6 = {s: (pop6[s] / sum(pop6.values())) / (n6[s] / len(combo)) if n6[s] else 0.0 for s in pop6}

    def rw_share(rs: list[dict], w: dict) -> float:
        return sum(w[r["stratum"]] for r in rs if r["rust"]) / sum(w[r["stratum"]] for r in rs)

    bs, ts = share(sure), share(t_sure)
    result = dict(
        labelled=len(rows), unsure=len(rows) - len(sure),
        unsure_by_stratum={s: sum(r["stratum"] == s and r["human"] == "unsure" for r in rows) for s in BOX_POP},
        confusion={s: {h: sum(r["stratum"] == s and r["human"] == h for r in rows) for h in ("rust", "not_rust", "unsure")}
                   for s in BOX_POP},
        box_rust_share=dict(sample=bs, reweighted=rw_share(sure, w_box),
                            by_stratum={s: share([r for r in sure if r["stratum"] == s]) for s in BOX_POP}),
        text_rust_share=dict(sample=ts),
        box_minus_text_rust_share=dict(sample=round(bs["share"] - ts["share"], 3),
                                       ci=newcombe(bs["rust"], bs["n"], ts["rust"], ts["n"])),
        not_rust_rejected={k: dict(rejected=sum(not r[k] for r in sure if not r["rust"] and r[k] is not None),
                                   of=sum(1 for r in sure if not r["rust"] and r[k] is not None))
                           for k in ("low", "minimal", "open")},
        verifiers={k: _metrics(sure, k, w_box) for k in ("low", "minimal", "open")},
        combined=dict(
            note="text-prompt audit (89 sure) + box-only audit; six-stratum reweighting to all text + new box "
                 "candidates of the default pipeline",
            n=len(combo), rust_share_sample=share(combo), rust_share_reweighted=rw_share(combo, w6),
            not_rust_rejected={k: dict(rejected=sum(not r[k] for r in combo if not r["rust"] and r[k] is not None),
                                       of=sum(1 for r in combo if not r["rust"] and r[k] is not None),
                                       ci=wilson(sum(not r[k] for r in combo if not r["rust"] and r[k] is not None),
                                                 sum(1 for r in combo if not r["rust"] and r[k] is not None)))
                               for k in ("low", "minimal", "open")},
            verifiers={k: _metrics(combo, k, w6) for k in ("low", "minimal", "open")}),
        usd_fill=ledger.total(),
    )
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
