"""Muse Glimmer 30B verifier distillation on Modal (QLoRA, one H100). Plan and costs: docs/GLIMMER_PLAN.md.

Stages (each run alone, reported before the next):
    download  CPU: snapshot meta-models/Muse-Glimmer-30B (Apache 2.0) into the private volume
    smoke     H100: load 4-bit, zero-shot on held-out examples (parse rate, decision agreement with the teacher),
              then a few LoRA steps; reports tokens/s for the training estimate
    train     H100: LoRA training with a wall-clock budget; adapter saved to the volume (never published)

Data (``benchmark.glimmer_data``) is put into the volume with ``modal volume put``. Guards as for every Walkdown
GPU job: max one container, retries off, scale to zero, explicit timeouts.

    .venv\\Scripts\\modal.exe run modal_apps/glimmer.py::download
    .venv\\Scripts\\modal.exe run --detach modal_apps/glimmer.py::smoke
    .venv\\Scripts\\modal.exe run --detach modal_apps/glimmer.py::train --budget-min 180

GPU stages always run with ``--detach``: they finish or hit their function timeout even if the local client is
stopped, and write their result to the volume (``/results/<stage>.json``). After every job and after any local
stop: ``modal app list`` / ``modal container list``, stop anything left, log it.
"""

from __future__ import annotations

import json
import os
import time

import modal

REPO = "meta-models/Muse-Glimmer-30B"
VOL = "/vol"
BASE = f"{VOL}/base"
DATA = f"{VOL}/data"
ADAPTERS = f"{VOL}/adapters"
H100_PER_SECOND = 3.95 / 3600

app = modal.App("walkdown-glimmer")
volume = modal.Volume.from_name("walkdown-glimmer", create_if_missing=True)
cpu_image = modal.Image.debian_slim(python_version="3.12").pip_install("huggingface_hub==1.33.0", "hf_transfer==0.1.9")
gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.10.0", "torchvision", index_url="https://download.pytorch.org/whl/cu128")
    .pip_install("transformers==5.21.0", "peft==0.21.1", "bitsandbytes==0.50.1", "accelerate==1.14.0",
                 "pillow", "numpy<3")
)


def _load_env() -> None:
    if modal.is_local():
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)


_load_env()
hf_secret = modal.Secret.from_dict({"HF_TOKEN": os.environ.get("HF_TOKEN", "")})


@app.function(image=cpu_image, volumes={VOL: volume}, secrets=[hf_secret], timeout=3600, retries=0, cpu=4,
              memory=8192)
def download_weights() -> dict:
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    from huggingface_hub import snapshot_download
    t0 = time.time()
    path = snapshot_download(REPO, local_dir=BASE, token=os.environ["HF_TOKEN"],
                             allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja", "*.py"])
    volume.commit()
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs)
    return dict(gb=round(size / 1e9, 1), seconds=round(time.time() - t0))


def _load(adapter: str | None = None):
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True,
                             # transformers 5.21 matches skip patterns from the START of the full module path (or as
                             # a suffix), so the vision path is named by its full prefix and stays in BF16.
                             llm_int8_skip_modules=["model.vision_tower", "model.vision_adapter",
                                                    "model.vision_projection", "lm_head"])
    model = AutoModelForImageTextToText.from_pretrained(BASE, quantization_config=bnb, dtype=torch.bfloat16,
                                                        device_map="cuda:0")
    # Fail fast (before any generation) if a vision weight was quantized: 4-bit weights are stored as uint8 and
    # the vision tower casts its input to the patch-embedding weight dtype.
    bad = [n for n, p in model.named_parameters() if "vision" in n and p.dtype == torch.uint8]
    if bad:
        raise RuntimeError(f"vision weights quantized ({len(bad)}), e.g. {bad[:3]}")
    proc = AutoProcessor.from_pretrained(BASE)
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    return model, proc


def _hf_messages(ex: dict, with_target: bool) -> tuple[list[dict], list]:
    """Production messages -> HF chat format with PIL images (and the target as the assistant turn)."""
    import base64
    import io

    from PIL import Image
    images, msgs = [], []
    for m in ex["messages"]:
        if isinstance(m["content"], str):
            msgs.append({"role": m["role"], "content": [{"type": "text", "text": m["content"]}]})
            continue
        parts = []
        for p in m["content"]:
            if p["type"] == "text":
                parts.append({"type": "text", "text": p["text"]})
            else:
                img = Image.open(io.BytesIO(base64.b64decode(p["image_url"]["url"].split(",", 1)[1]))).convert("RGB")
                images.append(img)
                parts.append({"type": "image"})
        msgs.append({"role": m["role"], "content": parts})
    msgs[0]["content"][0]["text"] = "Reasoning strength: low\n\n" + msgs[0]["content"][0]["text"]
    if with_target:
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": ex["target"]}]})
    return msgs, images


def _batch(proc, ex: dict):
    """input_ids, attention, pixel inputs and labels (loss on the assistant answer only)."""
    msgs, images = _hf_messages(ex, with_target=True)
    full = proc.apply_chat_template(msgs, tokenize=False)
    prompt = proc.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
    enc = proc(text=[full], images=[images], return_tensors="pt")
    n_prompt = proc(text=[prompt], images=[images], return_tensors="pt")["input_ids"].shape[1]
    labels = enc["input_ids"].clone()
    labels[:, :n_prompt] = -100
    enc["labels"] = labels
    return enc


def _save_result(name: str, result: dict) -> dict:
    """Write the result to the volume: with ``modal run --detach`` the local client may be gone."""
    os.makedirs(f"{VOL}/results", exist_ok=True)
    with open(f"{VOL}/results/{name}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    volume.commit()
    return result


def _read(name: str, n: int | None = None) -> list[dict]:
    rows = []
    with open(f"{DATA}/{name}.jsonl", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
            if n and len(rows) >= n:
                break
    return rows


def _decide(text: str) -> bool | None:
    s, e = text.find("{"), text.rfind("}")
    try:
        return bool(json.loads(text[s:e + 1])["is_defect"])
    except Exception:  # noqa: BLE001
        return None


def _zero_shot(model, proc, rows: list[dict]) -> dict:
    import torch
    out = []
    t0 = time.time()
    for ex in rows:
        msgs, images = _hf_messages(ex, with_target=False)
        enc = proc(text=[proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)],
                   images=[images], return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=1200, do_sample=False)
        text = proc.decode(gen[0, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        out.append(dict(id=ex["id"], teacher_accept=ex["accept"], accept=_decide(text), chars=len(text)))
    valid = [r for r in out if r["accept"] is not None]
    return dict(n=len(out), parsed=len(valid), agree=sum(r["accept"] == r["teacher_accept"] for r in valid),
                seconds_per_example=round((time.time() - t0) / max(1, len(out)), 1), rows=out)


def _peft(model, r: int = 16):
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    names = {n.split(".")[-1] for n, _ in model.named_modules()}
    targets = [t for t in ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj") if t in names]
    cfg = LoraConfig(r=r, lora_alpha=2 * r, lora_dropout=0.05, task_type="CAUSAL_LM",
                     target_modules=rf".*language_model.*\.({'|'.join(targets)})")
    return get_peft_model(model, cfg), targets


def _train_loop(model, proc, rows: list[dict], *, epochs: float, lr: float, accum: int, budget_s: float,
                max_tokens: int = 4096) -> dict:
    import math

    import torch
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=0.0)
    steps_total = math.ceil(len(rows) * epochs / accum)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, steps_total)))))
    model.train()
    t0, tokens, seen, losses, skipped = time.time(), 0, 0, [], 0
    order = [rows[i % len(rows)] for i in range(int(len(rows) * epochs))]
    for i, ex in enumerate(order):
        if time.time() - t0 > budget_s:
            break
        b = _batch(proc, ex)
        if b["input_ids"].shape[1] > max_tokens:
            skipped += 1
            continue
        b = {k: v.to("cuda:0") for k, v in b.items()}
        loss = model(**b).loss / accum
        loss.backward()
        tokens += int(b["input_ids"].shape[1])
        seen += 1
        losses.append(float(loss) * accum)
        if seen % accum == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
    wall = time.time() - t0
    return dict(examples=seen, skipped_too_long=skipped, tokens=tokens, wall_s=round(wall), tokens_per_s=round(tokens / max(wall, 1)),
                examples_per_s=round(seen / max(wall, 1), 3), loss_first10=round(sum(losses[:10]) / max(1, len(losses[:10])), 4),
                loss_last10=round(sum(losses[-10:]) / max(1, len(losses[-10:])), 4), completed=seen + skipped >= len(order))


@app.function(image=gpu_image, gpu="H100", volumes={VOL: volume}, timeout=2400, retries=0, max_containers=1)
def smoke_run(zero_shot_n: int = 20, train_steps: int = 10) -> dict:
    t0 = time.time()
    model, proc = _load()
    load_s = time.time() - t0
    held = _read("heldout")
    rng_rows = held[:zero_shot_n]
    zs = _zero_shot(model, proc, rng_rows)
    model, targets = _peft(model)
    tr = _train_loop(model, proc, _read("train", train_steps * 4), epochs=1, lr=1e-4, accum=4, budget_s=900)
    wall = time.time() - t0
    return _save_result("smoke", dict(load_s=round(load_s), lora_targets=targets,
                                      zero_shot={k: v for k, v in zs.items() if k != "rows"}, zero_shot_rows=zs["rows"],
                                      train=tr, wall_s=round(wall), usd_estimate=round(wall * H100_PER_SECOND, 2)))


@app.function(image=gpu_image, gpu="H100", volumes={VOL: volume}, timeout=4 * 3600, retries=0, max_containers=1)
def train_run(budget_min: float, epochs: float = 2.0, lr: float = 1e-4, run: str = "v1") -> dict:
    t0 = time.time()
    model, proc = _load()
    model, targets = _peft(model)
    rows = _read("train")
    tr = _train_loop(model, proc, rows, epochs=epochs, lr=lr, accum=16, budget_s=budget_min * 60 - (time.time() - t0) - 300)
    path = f"{ADAPTERS}/{run}"
    model.save_pretrained(path)
    volume.commit()
    wall = time.time() - t0
    return _save_result(f"train_{run}", dict(run=run, adapter=path, lora_targets=targets, train=tr, wall_s=round(wall),
                                             usd_estimate=round(wall * H100_PER_SECOND, 2)))


@app.local_entrypoint()
def download() -> None:
    print(json.dumps(download_weights.remote()))


@app.local_entrypoint()
def smoke(zero_shot_n: int = 20, train_steps: int = 10) -> None:
    print(json.dumps(smoke_run.remote(zero_shot_n, train_steps)))


@app.local_entrypoint()
def train(budget_min: float = 180, epochs: float = 2.0, run: str = "v1") -> None:
    print(json.dumps(train_run.remote(budget_min, epochs, run=run)))
