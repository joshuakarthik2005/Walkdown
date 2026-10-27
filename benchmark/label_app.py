"""Local-only labelling page for auditing SAM candidates (never deployed).

Shows ~100 stratified candidates one at a time (crop with the mask outlined,
plus a frame thumbnail) with three buttons: rust / not rust / unsure
(keys 1 / 2 / 3, u = undo). The dataset label and the verifier's verdict are
hidden so they cannot bias the labeller. Images are rendered on the fly from
WALKDOWN_DATA_DIR and are never written into the repo; labels are appended
to WALKDOWN_DATA_DIR/labels/audit.jsonl.

    .venv\\Scripts\\python.exe -m benchmark.label_app            # http://127.0.0.1:8001
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from backend.perception.sam import parse_output
from backend.verify.crops import candidate_crop, context_thumbnail
from benchmark.download_dataset import DATA_DIR, RAW_DIR
from benchmark.sam_dryrun import RUN_DIR as SAM_DIR, ground_truth
from benchmark.splits import SEED, load_split
from benchmark.verify_eval import label

LABEL_DIR = DATA_DIR / "labels"
SAMPLE_PATH = LABEL_DIR / "audit_sample.json"
LABELS_PATH = LABEL_DIR / "audit.jsonl"
PER_STRATUM = {"TP": 40, "FP": 40, "ambiguous": 20}


def build_sample() -> list[dict]:
    """Stratified sample of test candidates by coverage label, built once and saved (seeded)."""
    if SAMPLE_PATH.exists():
        return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    # Visit test images in a seeded random order and take at most 2 candidates per image per stratum
    # until every stratum is full: only the visited images' masks are decoded (decoding is slow).
    rng = random.Random(SEED)
    images = load_split("test")
    rng.shuffle(images)
    picked: dict[str, list[dict]] = {k: [] for k in PER_STRATUM}
    for rel in images:
        if all(len(picked[k]) >= n for k, n in PER_STRATUM.items()):
            break
        path = SAM_DIR / "rust" / (Path(rel).stem + ".txt")
        if not path.exists():
            continue
        gt = ground_truth([rel])[rel]
        union = np.logical_or.reduce(gt) if gt else np.zeros((640, 640), bool)
        per_image: dict[str, int] = {}
        insts = parse_output(path.read_text(encoding="utf-8"), 640, 640)
        rng.shuffle(insts)
        for inst in insts:
            lab, cov = label(inst.mask, union)
            if len(picked[lab]) >= PER_STRATUM[lab] or per_image.get(lab, 0) >= 2:
                continue
            per_image[lab] = per_image.get(lab, 0) + 1
            picked[lab].append(dict(id=f"{Path(rel).stem}#{inst.object_id}", image=rel, object_id=inst.object_id,
                                    coverage_label=lab, coverage=round(cov, 3)))
    sample = [c for k in PER_STRATUM for c in picked[k]]
    rng.shuffle(sample)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_PATH.write_text(json.dumps(sample, indent=1), encoding="utf-8")
    return sample


def read_labels() -> dict[str, dict]:
    """Latest label per candidate (later lines win; 'undo' removes)."""
    out: dict[str, dict] = {}
    if LABELS_PATH.exists():
        for line in LABELS_PATH.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["label"] == "undo":
                out.pop(r["id"], None)
            else:
                out[r["id"]] = r
    return out


app = FastAPI(title="Walkdown audit labelling (local only)")
_SAMPLE: list[dict] = []


def sample() -> list[dict]:
    """The audit sample, built on first use (needs the SAM test cache)."""
    if not _SAMPLE:
        _SAMPLE.extend(build_sample())
    return _SAMPLE


def by_id() -> dict[str, dict]:
    return {c["id"]: c for c in sample()}


def _instance(cid: str):
    c = by_id().get(cid)
    if c is None:
        raise HTTPException(404)
    text = (SAM_DIR / "rust" / (Path(c["image"]).stem + ".txt")).read_text(encoding="utf-8")
    inst = next(i for i in parse_output(text, 640, 640) if i.object_id == c["object_id"])
    return cv2.imread(str(RAW_DIR / c["image"]), cv2.IMREAD_COLOR), inst


CROP_DIR = LABEL_DIR / "crops"


def render(cid: str) -> None:
    """Render and cache the crop and thumbnail for one candidate (mask decoding is slow, so do it once)."""
    img, inst = _instance(cid)
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    stem = cid.replace("#", "__")
    cv2.imwrite(str(CROP_DIR / f"{stem}_crop.png"), candidate_crop(img, inst.mask, inst.box))
    cv2.imwrite(str(CROP_DIR / f"{stem}_thumb.png"), context_thumbnail(img, inst.box, side=320))


@app.get("/img/{cid}/{kind}.png")
def image(cid: str, kind: str) -> Response:
    if kind not in ("crop", "thumb"):
        raise HTTPException(404)
    path = CROP_DIR / f"{cid}_{kind}.png"
    if not path.exists():
        render(cid.replace("__", "#"))
    return Response(path.read_bytes(), media_type="image/png")


@app.get("/next")
def next_item() -> dict:
    done = read_labels()
    todo = [c["id"] for c in sample() if c["id"] not in done]
    return dict(id=todo[0].replace("#", "__") if todo else None, done=len(done), total=len(sample()))


class LabelIn(BaseModel):
    id: str
    label: str


@app.post("/label")
def post_label(body: LabelIn) -> dict:
    cid = body.id.replace("__", "#")
    if cid not in by_id() or body.label not in ("rust", "not_rust", "unsure", "undo"):
        raise HTTPException(400)
    with LABELS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(id=cid, label=body.label, t=time.time())) + "\n")
    return dict(ok=True)


@app.get("/last")
def last_labelled() -> dict:
    done = read_labels()
    last = max(done.values(), key=lambda r: r["t"], default=None)
    return dict(id=last["id"].replace("#", "__") if last else None)


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Walkdown audit labels</title>
<style>body{font-family:system-ui,sans-serif;margin:24px;background:#111;color:#eee}
.row{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}img{border:1px solid #444;max-width:100%}
button{font-size:18px;padding:10px 18px;margin-right:8px;border-radius:6px;border:0;cursor:pointer}
.r{background:#c0562b;color:#fff}.n{background:#2b7cc0;color:#fff}.u{background:#666;color:#fff}
#p{margin:8px 0 16px;color:#aaa}</style></head><body>
<h2>Is the region outlined in cyan rust or corrosion?</h2>
<div id="p"></div>
<div class="row"><img id="crop" width="448"><img id="thumb" width="320"></div>
<p><button class="r" onclick="send('rust')">1 · rust</button><button class="n" onclick="send('not_rust')">2 · not rust</button>
<button class="u" onclick="send('unsure')">3 · unsure</button><button onclick="undo()">u · undo last</button></p>
<p style="color:#888">Judge only what is inside the outline. Rust staining from a corroding part counts as rust;
orange paint, dirt, shadows, wood and reflections do not.</p>
<script>
let cur=null;
async function load(){const r=await (await fetch('/next')).json();
 document.getElementById('p').textContent=`${r.done} / ${r.total} labelled`;
 if(!r.id){document.getElementById('crop').removeAttribute('src');document.getElementById('thumb').removeAttribute('src');
  document.querySelector('h2').textContent='All done. Thank you.';cur=null;return;}
 cur=r.id;document.getElementById('crop').src=`/img/${cur}/crop.png`;document.getElementById('thumb').src=`/img/${cur}/thumb.png`;}
async function send(l){if(!cur)return;await fetch('/label',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({id:cur,label:l})});load();}
async function undo(){const r=await (await fetch('/last')).json();if(!r.id)return;
 await fetch('/label',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:r.id,label:'undo'})});load();}
document.addEventListener('keydown',e=>{if(e.key==='1')send('rust');if(e.key==='2')send('not_rust');
 if(e.key==='3')send('unsure');if(e.key==='u')undo();});
load();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE


if __name__ == "__main__":
    import sys

    import uvicorn

    if "--prewarm" in sys.argv:  # render every crop once, before labelling
        for i, c in enumerate(sample()):
            if not (CROP_DIR / f"{c['id'].replace('#', '__')}_crop.png").exists():
                render(c["id"])
            print(f"{i + 1}/{len(sample())}", flush=True)
        sys.exit(0)

    uvicorn.run(app, host="127.0.0.1", port=8001)  # loopback only: never expose dataset images
