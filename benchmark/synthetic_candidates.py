"""Candidates on the FLUX training negatives: SAM 3.1 open weights (Modal) segment the LOOK-ALIKE object itself
("orange arrow", "wooden plank", "copper tube", ...), so every mask is a true negative by construction.

A first harvest with the production prompts "rust" / "brown stain" was set aside
(runs/sam_open/flux_train_rust_prompt_set_aside): FLUX adds rust traces at seams, ladders and pipe ends despite
the prompt, and the "rust" masks landed on exactly those, which would have been real-looking rust labelled "not a
defect". "wet patches after rain" is excluded for the same reason (FLUX draws rust streaks).
Output per image: RLE records in WALKDOWN_DATA_DIR/runs/sam_open/flux_train/, read by benchmark.glimmer_data.

Training data only: these images and candidates never enter a test set.

    .venv\\Scripts\\python.exe -m benchmark.synthetic_candidates
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.clients.cost import CostLedger
from backend.perception.sam_open import segment_images_open
from benchmark.download_dataset import DATA_DIR
from benchmark.glimmer_data import AMBIGUOUS_LOOKALIKES, FLUX_DIR, FLUX_SAM

LOOKALIKE_PROMPTS = {
    "glossy orange safety paint": "orange paint", "fresh red-brown primer paint": "red-brown paint",
    "orange identification tape and labels": "orange tape", "a wooden plank leaning against it": "wooden plank",
    "warm sunset light reflections": "light reflection", "an orange flow-direction arrow painted on it": "orange arrow",
    "copper-coloured tubing next to it": "copper tube", "strong diagonal shadows": "shadow",
    "dust and leaf litter at the base": "dry leaves",
}
BATCH = 50


def main() -> int:
    man = [json.loads(l) for l in (FLUX_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    man = [m for m in man if m["lookalike"] in LOOKALIKE_PROMPTS and m["lookalike"] not in AMBIGUOUS_LOOKALIKES]
    FLUX_SAM.mkdir(parents=True, exist_ok=True)
    ledger = CostLedger(DATA_DIR / "runs" / "cost_ledger.jsonl")
    by_prompt: dict[str, list] = {}
    for m in man:
        if not (FLUX_SAM / (Path(m["file"]).stem + ".json")).exists():
            by_prompt.setdefault(LOOKALIKE_PROMPTS[m["lookalike"]], []).append(FLUX_DIR / m["file"])
    print(f"{len(man)} usable images, {sum(map(len, by_prompt.values()))} to segment", flush=True)
    for prompt, paths in by_prompt.items():
        for i in range(0, len(paths), BATCH):
            batch = paths[i:i + BATCH]
            for path, recs in zip(batch, segment_images_open(batch, prompt, ledger=ledger, job="synthetic-flux-sam-open")):
                recs = [{**r, "prompt": prompt} for r in recs]
                (FLUX_SAM / f"{path.stem}.json").write_text(json.dumps(recs), encoding="utf-8")
            print(f"{prompt}: {i + len(batch)}/{len(paths)}", flush=True)
    n = sum(len(json.loads((FLUX_SAM / (Path(m["file"]).stem + ".json")).read_text(encoding="utf-8"))) for m in man
            if (FLUX_SAM / (Path(m["file"]).stem + ".json")).exists())
    print(json.dumps(dict(images=len(man), candidates=n, modal_usd=round(ledger.total(), 3))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
