"""FLUX.1-schnell (Apache 2.0, black-forest-labs) on Modal: synthetic hard negatives for TRAINING only (F6).

Generates plant surfaces with rust look-alikes and no corrosion from ``benchmark.synthetic_prompts`` (train split).
The weights are downloaded once into a private Modal volume with the builder's HF token (gated repo, auto-approved
licence acceptance). Images are returned as JPEG bytes; the caller writes them to G: and labels them synthetic.

Same guards as every Walkdown GPU job: one container at most, retries off, scale to zero.

    .venv\Scripts\python.exe -m modal deploy modal_apps/flux_negatives.py
"""

from __future__ import annotations

import os

import modal

MODEL = "black-forest-labs/FLUX.1-schnell"
CACHE = "/hf"

app = modal.App("walkdown-flux")
volume = modal.Volume.from_name("walkdown-flux-weights", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.10.0", index_url="https://download.pytorch.org/whl/cu128")
    .pip_install("diffusers==0.32.2", "transformers==4.48.0", "accelerate==1.3.0", "sentencepiece==0.2.0",
                 "protobuf==5.29.3", "huggingface_hub==0.27.1", "pillow")
    .env({"HF_HOME": CACHE})
)


def _load_env() -> None:
    if modal.is_local():
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)


_load_env()
hf_secret = modal.Secret.from_dict({"HF_TOKEN": os.environ.get("HF_TOKEN", "")})


@app.cls(image=image, gpu="L40S", volumes={CACHE: volume}, secrets=[hf_secret], scaledown_window=120, retries=0,
         timeout=3600, max_containers=1)
class Flux:
    @modal.enter()
    def load(self) -> None:
        import torch
        from diffusers import FluxPipeline
        self.pipe = FluxPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16, token=os.environ["HF_TOKEN"])
        self.pipe.to("cuda")
        volume.commit()

    @modal.method()
    def generate(self, items: list[dict], size: int = 768) -> list[bytes]:
        """One JPEG per prompt record ({prompt, seed}); 4 steps, no guidance (schnell defaults)."""
        import io

        import torch
        out = []
        for it in items:
            img = self.pipe(it["prompt"], num_inference_steps=4, guidance_scale=0.0, height=size, width=size,
                            max_sequence_length=256,
                            generator=torch.Generator("cuda").manual_seed(int(it["seed"]))).images[0]
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            out.append(buf.getvalue())
        return out
