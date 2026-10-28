"""Training data for the Muse Glimmer verifier distillation (open-weights data only; see docs/GLIMMER_PLAN.md).

Each example is exactly the production verifier request (Muse Spark Open variant: SYSTEM_PROMPT + JSON
instruction, the candidate text line, the cyan-outlined crop and the frame thumbnail) and a target grade JSON.
Images are re-encoded as JPEG (q 90) to keep the file small.

Sources:
1. **Teacher labels** on the clean train pool: SAM 3.1 open-weights candidates graded by Muse Spark Open
   (``benchmark.teacher_labels``). Target = the teacher's grade.
2. **Synthetic hard negatives** (F6): FLUX.1-schnell images of intact plant metal with rust look-alikes
   (``benchmark.synthetic_negatives flux``), candidates from SAM 3.1 open weights (``--synthetic-candidates``).
   Target = a constructed rejection (is_defect false, severity 1, no_action) naming the look-alike. Categories a
   person could read as real rust staining (water stains, paint drips, oil smudges, mud, dirt smears) are left
   out: on a visual check FLUX renders them like rust.
Never included: hosted Meta model outputs, dev/test images, audit labels, public Roboflow negatives.

Split: 10% of the train pool's source clusters (Roboflow source name) are held out for evaluation and early
stopping; synthetic images are split 90/10 by image. The training split is balanced: both classes are capped at
the smaller one, keeping every real rejection first (seeded).

    .venv\\Scripts\\python.exe -m benchmark.glimmer_data
"""

from __future__ import annotations

import base64
import io
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from backend.perception.sam_open import to_instances
from backend.verify.verifier import JSON_INSTRUCTION, SYSTEM_PROMPT, Candidate, _user_content
from benchmark.download_dataset import DATA_DIR, RAW_DIR

OUT = DATA_DIR / "glimmer" / "data"
JOURNAL = DATA_DIR / "runs" / "teacher_train_pool_journal.jsonl"
SAM_TEXT = DATA_DIR / "runs" / "sam_open" / "rust"
FLUX_DIR = DATA_DIR / "synthetic" / "flux_train"
FLUX_SAM = DATA_DIR / "runs" / "sam_open" / "flux_train"
HELDOUT_SHARE = 0.10
MAX_SYNTHETIC_PER_IMAGE = 3  # largest look-alike masks first; avoids a few images dominating
SEED = 20261028
# Look-alikes a person (or the image generator) can render as real rust staining: never used as "not a defect".
AMBIGUOUS_LOOKALIKES = {"dark water stains running down the surface", "brown paint drips", "brown oil smudges",
                        "dried mud splashes", "safety yellow paint with brown dirt smears",
                        "wet patches after rain"}


def _jpeg(data_url: str) -> str:
    img = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _example(cid: str, image: np.ndarray, inst, target: dict, **meta) -> dict:
    content = _user_content(Candidate(cid, image, inst.mask, inst.box, inst.confidence))
    for part in content:
        if part["type"] == "image_url":
            part["image_url"]["url"] = _jpeg(part["image_url"]["url"])
    return dict(id=cid, accept=bool(target["is_defect"]), target=json.dumps(target),
                messages=[{"role": "system", "content": SYSTEM_PROMPT + JSON_INSTRUCTION},
                          {"role": "user", "content": content}], **meta)


def teacher_examples() -> list[dict]:
    out = []
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        rel = r["image"]
        insts = {i.object_id: i for i in to_instances(json.loads((SAM_TEXT / (Path(rel).stem + ".json"))
                                                                 .read_text(encoding="utf-8")), frame=0)}
        image = cv2.imread(str(RAW_DIR / rel), cv2.IMREAD_COLOR)
        for row in r["rows"]:
            if not row["grade"] or row["object_id"] not in insts:
                continue
            out.append(_example(row["id"], image, insts[row["object_id"]], row["grade"], source="teacher",
                                cluster=Path(rel).name.split(".rf.")[0]))
    return out


def synthetic_examples() -> list[dict]:
    """Constructed rejections on FLUX hard negatives (empty until those images and their candidates exist)."""
    man = FLUX_DIR / "manifest.jsonl"
    if not man.exists() or not FLUX_SAM.exists():
        return []
    out = []
    for line in man.read_text(encoding="utf-8").splitlines():
        m = json.loads(line)
        if m["lookalike"] in AMBIGUOUS_LOOKALIKES or m.get("subset") != "train":  # "tune" is for prompt hardening
            continue
        sam = FLUX_SAM / (Path(m["file"]).stem + ".json")
        if not sam.exists():
            continue
        image = cv2.imread(str(FLUX_DIR / m["file"]), cv2.IMREAD_COLOR)
        h, w = image.shape[:2]
        insts = sorted(to_instances(json.loads(sam.read_text(encoding="utf-8")), frame=0), key=lambda i: -i.area)
        for inst in insts[:MAX_SYNTHETIC_PER_IMAGE]:
            pct = 100 * inst.mask.sum() / (h * w)
            target = {"is_defect": False, "defect_type": "none", "severity": 1, "confidence": 0.9,
                      "evidence": {"visual_cues": [f"{m['lookalike']} on intact metal, not corrosion",
                                                   "no orange-brown granular oxide, scale, pitting, flaking or "
                                                   "section loss inside the outline"],
                                   "location": m["subject"], "extent": f"region covers {pct:.2f}% of the frame; "
                                   "no material loss", "mask_fit": "good"},
                      "recommended_action": "no_action"}
            out.append(_example(f"{Path(m['file']).stem}#{inst.object_id}", image, inst, target, source="synthetic",
                                cluster=m["file"], lookalike=m["lookalike"]))
    return out


def main() -> int:
    rng = random.Random(SEED)
    teacher, synth = teacher_examples(), synthetic_examples()
    clusters = sorted({e["cluster"] for e in teacher})
    held = set(rng.sample(clusters, max(1, round(HELDOUT_SHARE * len(clusters)))))
    s_clusters = sorted({e["cluster"] for e in synth})
    held |= set(rng.sample(s_clusters, round(HELDOUT_SHARE * len(s_clusters)))) if s_clusters else set()
    heldout = [e for e in teacher + synth if e["cluster"] in held]
    train = [e for e in teacher + synth if e["cluster"] not in held]
    acc, rej = [e for e in train if e["accept"]], [e for e in train if not e["accept"]]
    rng.shuffle(acc)
    real_rej = [e for e in rej if e["source"] != "synthetic"]
    syn_rej = [e for e in rej if e["source"] == "synthetic"]
    rng.shuffle(syn_rej)
    n = min(len(acc), len(rej))  # balanced: both classes capped at the smaller one; real rejects kept first
    rej_kept = (real_rej + syn_rej)[:n]
    balanced = rej_kept + acc[:n]
    rng.shuffle(balanced)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", balanced), ("heldout", heldout)):
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for e in rows:
                f.write(json.dumps(e) + "\n")
    summary = dict(teacher=len(teacher), synthetic=len(synth), heldout=len(heldout),
                   heldout_accept=sum(e["accept"] for e in heldout),
                   train_before_balance=dict(accept=len(acc), reject=len(rej),
                                             synthetic_reject=sum(e["source"] == "synthetic" for e in rej)),
                   train=len(balanced), train_accept=sum(e["accept"] for e in balanced),
                   mb={n: round((OUT / f"{n}.jsonl").stat().st_size / 1e6, 1) for n in ("train", "heldout")})
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__" and "--eval" not in sys.argv:
    sys.exit(main())


def build_eval() -> dict:
    """Evaluation file for Glimmer (zero-shot and tuned): production requests + labels, never trained on.

    Sets: the builder's audits (sure labels), Cloud candidates of the real public negatives and of the Muse Image
    stress set, and every 12th text-prompt test candidate (coverage label + cached hosted/Open decisions).
    """
    from benchmark.fireworks_eval import test_candidates
    from benchmark.verifier_hardening import audited, negatives_cloud

    def example(c, **meta) -> dict:
        content = _user_content(c)
        for part in content:
            if part["type"] == "image_url":
                part["image_url"]["url"] = _jpeg(part["image_url"]["url"])
        return dict(id=c.candidate_id, messages=[{"role": "system", "content": SYSTEM_PROMPT + JSON_INSTRUCTION},
                                                 {"role": "user", "content": content}], **meta)

    rows = []
    for rust, c in audited():
        rows.append(example(c, set="audit", human_rust=rust, source=c.source))
    for name, set_name in (("public", "public"), ("muse_eval", "synthetic_muse")):
        for img, c in negatives_cloud(set_name):
            rows.append(example(c, set=name, image=img, source=c.source))
    for r, lazy in test_candidates()[::12]:
        rows.append(example(lazy.load(), set="test", coverage_label=r["label"]))
    with (OUT / "eval.jsonl").open("w", encoding="utf-8") as f:
        for e in rows:
            f.write(json.dumps(e) + "\n")
    import collections
    return dict(rows=len(rows), by_set=dict(collections.Counter(e["set"] for e in rows)),
                mb=round((OUT / "eval.jsonl").stat().st_size / 1e6, 1))


if __name__ == "__main__" and "--eval" in sys.argv:
    print(json.dumps(build_eval(), indent=1))
