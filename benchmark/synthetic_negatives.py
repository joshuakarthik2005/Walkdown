"""Generate the two synthetic hard-negative sets (see ``benchmark.synthetic_prompts``).

    flux  ~1,000 TRAINING negatives, FLUX.1-schnell open weights on Modal  -> synthetic/flux_train/
    muse  ~300 EVALUATION-ONLY negatives, Muse Image (Meta Model API)      -> synthetic/muse_eval/

Images are resized to 640 px (the dataset's size) and written to WALKDOWN_DATA_DIR, never into the repo. Each set
has a ``manifest.jsonl`` with ``synthetic: true``, the generator, its licence/terms, the allowed use and the prompt.
Resumable: existing files are skipped.

    .venv\\Scripts\\python.exe -m benchmark.synthetic_negatives muse --n 20 --max-usd 0.3
    .venv\\Scripts\\python.exe -m benchmark.synthetic_negatives flux --n 1000
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from backend.clients.cost import CostEntry, CostLedger
from benchmark.download_dataset import DATA_DIR
from benchmark.synthetic_prompts import prompts

OUT = DATA_DIR / "synthetic"
LEDGER = DATA_DIR / "runs" / "cost_ledger.jsonl"
SETS = {
    "flux": dict(dir="flux_train", split="train", generator="FLUX.1-schnell (black-forest-labs), Modal L40S",
                 licence="Apache 2.0", use="training/tuning only (subset tune: verifier-prompt hardening; subset "
                 "train: Glimmer verifier, SAM LoRA); never in any test set"),
    "muse": dict(dir="muse_eval", split="eval", generator="muse-image-1.0 (Meta Model API)",
                 licence="Meta Model API terms (10.1(ix): evaluation only)",
                 use="evaluation only (false-alarm stress test); never used for training"),
}
MUSE_USD = 0.01  # per generated image (dev.meta.ai pricing)
L40S_PER_SECOND = 1.95 / 3600
SIZE = 640


def _save(jpg_or_png: bytes, path: Path) -> None:
    img = Image.open(io.BytesIO(jpg_or_png)).convert("RGB")
    img.thumbnail((SIZE, SIZE))
    img.save(path, format="JPEG", quality=92)


TUNE_SHARE = 0.30  # FLUX images: ~30% "tune" (verifier-prompt hardening), ~70% "train" (Glimmer, SAM LoRA)


def flux_subset(rec_id: str) -> str:
    """Deterministic tune/train split of the FLUX set by image id (seeded hash, no shared images)."""
    import hashlib
    h = int(hashlib.sha256(f"flux-split-{rec_id}".encode()).hexdigest(), 16) % 1000
    return "tune" if h < TUNE_SHARE * 1000 else "train"


def _manifest(d: Path, rec: dict, meta: dict) -> None:
    if meta is SETS["flux"]:
        rec = {**rec, "subset": flux_subset(rec["id"])}
    with (d / "manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(file=f"{rec['id']}.jpg", synthetic=True, generator=meta["generator"],
                                licence=meta["licence"], use=meta["use"], **rec)) + "\n")


def run_muse(recs: list[dict], d: Path, ledger: CostLedger, max_usd: float) -> None:
    from backend.clients.meta import meta_client, with_retries

    def one(rec: dict) -> str | None:
        if ledger.total() + MUSE_USD > max_usd:
            return None
        try:
            resp = with_retries(lambda: meta_client().images.generate(model="muse-image-1.0", prompt=rec["prompt"],
                                                                      n=1, size="1024x1024", output_format="jpeg"))
        except Exception as err:  # noqa: BLE001  a safety block or failure skips this prompt (not billed)
            return f"{rec['id']}: {type(err).__name__}: {str(err)[:150]}"
        ledger.add(CostEntry(job="synthetic-muse-eval", model="muse-image-1.0", usd=MUSE_USD, images=1))
        _save(base64.b64decode(resp.data[0].b64_json), d / f"{rec['id']}.jpg")
        _manifest(d, rec, SETS["muse"])
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        for err in pool.map(one, recs):
            if err:
                print(err, flush=True)


# FLUX ignores negation: "no rust, no corrosion" in the prompt produced rusty metal on a first 30-image batch
# (set aside in synthetic/flux_train_negation_prompt_set_aside). FLUX prompts therefore never mention rust and
# describe new, intact, freshly coated metal instead.
FLUX_STYLE = ("Realistic handheld inspection photo, close to medium range, sharp focus. The metal is brand new and "
              "factory clean: smooth intact glossy coating, bright clean steel, recently installed equipment.")


def flux_prompt(rec: dict) -> str:
    return f"{rec['subject']} with {rec['lookalike']}, {rec['context']}. {FLUX_STYLE}"


def run_flux(recs: list[dict], d: Path, ledger: CostLedger, batch: int = 50) -> None:
    import modal
    flux = modal.Cls.from_name("walkdown-flux", "Flux")()
    for i in range(0, len(recs), batch):
        part = recs[i:i + batch]
        t0 = time.perf_counter()
        images = flux.generate.remote([dict(prompt=flux_prompt(r), seed=r["seed"]) for r in part])
        secs = time.perf_counter() - t0
        ledger.add(CostEntry(job="synthetic-flux-train", model="FLUX.1-schnell (Modal L40S)",
                             usd=secs * L40S_PER_SECOND, images=len(part)))
        for rec, jpg in zip(part, images):
            _save(jpg, d / f"{rec['id']}.jpg")
            _manifest(d, {**rec, "prompt": flux_prompt(rec)}, SETS["flux"])
        print(f"{i + len(part)}/{len(recs)} ({secs:.0f} s, {secs / len(part):.1f} s/image)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("set", choices=sorted(SETS))
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--max-usd", type=float, default=3.5)
    args = ap.parse_args()
    meta = SETS[args.set]
    d = OUT / meta["dir"]
    d.mkdir(parents=True, exist_ok=True)
    recs = [r for r in prompts(meta["split"], args.n) if not (d / f"{r['id']}.jpg").exists()]
    if args.set == "flux":  # training negatives: only look-alikes that render without rust (glimmer_data)
        from benchmark.glimmer_data import AMBIGUOUS_LOOKALIKES
        recs = [r for r in recs if r["lookalike"] not in AMBIGUOUS_LOOKALIKES]
    ledger = CostLedger(LEDGER)
    print(f"{len(recs)} to generate into {d}", flush=True)
    if args.set == "muse":
        run_muse(recs, d, ledger, args.max_usd)
    else:
        run_flux(recs, d, ledger)
    print(json.dumps(dict(set=args.set, images=len(list(d.glob("*.jpg"))), usd=round(ledger.total(), 4))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
