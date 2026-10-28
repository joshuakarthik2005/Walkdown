"""Prompts for synthetic hard negatives: plant surfaces with rust look-alikes and no corrosion.

Two separate sets with two separate generators, never mixed:
- **training** (F6): FLUX.1-schnell open weights on Modal (``modal_apps/flux_negatives.py``), for the Glimmer
  verifier and the SAM LoRA only;
- **evaluation stress test**: Muse Image (``muse-image-1.0``, Meta Model API). Hosted outputs are used only for
  evaluation (Meta Model API terms 10.1(ix)) and are never trained on.
Training on one generator and testing on the other avoids rewarding generator-specific artefacts.

Every image is synthetic, labelled so in its manifest, and never part of any dev/test split of real images.
"""

from __future__ import annotations

import itertools
import random

SUBJECTS = [
    "a horizontal steel process pipe on a pipe rack", "a large vertical storage tank shell", "a gate valve with handwheel",
    "a bolted pipe flange joint", "a steel pipe support and clamp", "a painted steel handrail on a platform",
    "a pump casing and its connected piping", "an insulated pipe with metal cladding", "an elbow in a pipe run",
    "a steel ladder on a tank", "a pressure vessel nozzle", "a row of parallel pipes in a pipe rack",
]
LOOKALIKES = [
    "glossy orange safety paint", "fresh red-brown primer paint", "safety yellow paint with brown dirt smears",
    "dark water stains running down the surface", "wet patches after rain", "strong diagonal shadows",
    "dried mud splashes", "orange identification tape and labels", "a wooden plank leaning against it",
    "warm sunset light reflections", "brown paint drips", "dust and leaf litter at the base",
    "an orange flow-direction arrow painted on it", "brown oil smudges", "copper-coloured tubing next to it",
]
CONTEXT = ["in a refinery", "in a tank farm", "at a pump station", "in a power plant", "at an oil terminal"]
STYLE = ("realistic handheld inspection photo, close to medium range, sharp focus. The metal is intact and "
         "well maintained: no rust, no corrosion, no flaking, no pitting.")


EVAL_COMBOS = 300  # the evaluation set's prompt combinations are never used for training
SEED = 20261028


def prompts(split: str, n: int) -> list[dict]:
    """``n`` prompt records for ``split`` ("train" or "eval"). The (subject, look-alike, context) combinations are
    shuffled once; eval takes the first EVAL_COMBOS, train cycles through the rest, so no prompt is shared."""
    combos = list(itertools.product(SUBJECTS, LOOKALIKES, CONTEXT))
    random.Random(SEED).shuffle(combos)
    pool = combos[:EVAL_COMBOS] if split == "eval" else combos[EVAL_COMBOS:]
    out = []
    for i in range(n):
        s, l, c = pool[i % len(pool)]
        out.append(dict(id=f"{split}{i:04d}", subject=s, lookalike=l, context=c, seed=SEED + i,
                        prompt=f"{s} with {l}, {c}. {STYLE}"))
    return out
