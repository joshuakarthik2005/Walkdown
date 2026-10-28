"""Candidates on the FLUX training negatives: SAM 3.1 open weights (Modal), production prompt "rust" plus
"brown stain" to collect more look-alike masks. Output per image: RLE records (object ids made unique across
prompts) in WALKDOWN_DATA_DIR/runs/sam_open/flux_train/, read by benchmark.glimmer_data.

Training data only: these images and candidates never enter a test set.

    .venv\\Scripts\\python.exe -m benchmark.synthetic_candidates
"""

from __future__ import annotations

import json
import sys

from backend.clients.cost import CostLedger
from backend.perception.sam_open import segment_images_open
from benchmark.download_dataset import DATA_DIR
from benchmark.glimmer_data import AMBIGUOUS_LOOKALIKES, FLUX_DIR, FLUX_SAM

PROMPTS = ("rust", "brown stain")
BATCH = 50


def main() -> int:
    man = [json.loads(l) for l in (FLUX_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    images = [FLUX_DIR / m["file"] for m in man if m["lookalike"] not in AMBIGUOUS_LOOKALIKES]
    FLUX_SAM.mkdir(parents=True, exist_ok=True)
    todo = [p for p in images if not (FLUX_SAM / f"{p.stem}.json").exists()]
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    print(f"{len(images)} usable images, {len(todo)} to segment", flush=True)
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        per_prompt = [segment_images_open(batch, p, ledger=ledger, job="synthetic-flux-sam-open") for p in PROMPTS]
        for k, path in enumerate(batch):
            recs = []
            for j, prompt_recs in enumerate(per_prompt):
                for r in prompt_recs[k]:
                    recs.append({**r, "obj_id": 1000 * j + int(r["obj_id"]), "prompt": PROMPTS[j]})
            (FLUX_SAM / f"{path.stem}.json").write_text(json.dumps(recs), encoding="utf-8")
        print(f"{i + len(batch)}/{len(todo)}", flush=True)
    n = sum(len(json.loads((FLUX_SAM / f"{p.stem}.json").read_text(encoding="utf-8"))) for p in images)
    print(json.dumps(dict(images=len(images), candidates=n, modal_usd=round(ledger.total(), 3))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
