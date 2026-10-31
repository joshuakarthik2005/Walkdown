"""SAM 3 full fine-tune on Modal (one H100): can corrosion segmentation from the text prompt "rust" be improved?

The pinned sam3 repo supports a full fine-tune of the SAM 3 *image* model only (``sam3/train/train.py``, Hydra +
submitit). This app derives a config from the repo's own ``roboflow_v100_full_ft_100_images.yaml`` inside the
container, with these changes and nothing else:
- data: ``/vol/data/rust/{train,test}`` (benchmark/sam3ft_data.py: 585 train-pool images + 621 FLUX-train
  negatives; dev 50 as the validation folder), one category "rust";
- segmentation on: ``scratch.enable_segmentation`` and the repo's own segmentation loss block (Boxes, IABCEMdetr,
  Masks), which the stock config ships commented out;
- one GPU, no cluster (``--use-cluster 0``), checkpoints saved, validation only at the end.

Evaluation (``evaluate``): base SAM 3 (HF checkpoint) or a fine-tuned checkpoint, ``Sam3Processor`` with the text
prompt "rust" at confidence 0.5 on the dev images; COCO RLE results go to ``/vol/results/eval_<tag>.json`` and are
scored locally (benchmark/sam3ft_score.py) against SAM 3.1 open weights.

Guards: max one container, retries off, hard timeouts, ``--detach``; check ``modal container list`` afterwards.

    .venv\\Scripts\\modal.exe run --detach modal_apps/sam3_finetune.py::train --epochs 1 --run smoke
    .venv\\Scripts\\modal.exe run --detach modal_apps/sam3_finetune.py::evaluate --tag base
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import modal

SAM3_COMMIT = "f1647e8d0c1d280991f4d1b7d974c2704537fe66"
VOL = "/vol"
H100_PER_SECOND = 3.95 / 3600

app = modal.App("walkdown-sam3ft")
volume = modal.Volume.from_name("walkdown-sam3ft", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .pip_install("torch==2.10.0", "torchvision", index_url="https://download.pytorch.org/whl/cu128")
    .run_commands(f"git clone https://github.com/facebookresearch/sam3.git /opt/sam3 && cd /opt/sam3 "
                  f"&& git checkout {SAM3_COMMIT} && pip install -e '.[train]'")
    .pip_install("huggingface_hub", "opencv-python-headless<4.12", "pycocotools", "numpy<2", "pillow", "einops",
                 "psutil", "decord", "scipy", "scikit-image", "tensorboard")
    .env({"HF_HOME": f"{VOL}/hf"})
)


def _load_env() -> None:
    if modal.is_local():
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)


_load_env()
hf_secret = modal.Secret.from_dict({"HF_TOKEN": os.environ.get("HF_TOKEN", "")})

SEG_LOSS = {
    "_target_": "sam3.train.loss.sam3_loss.Sam3LossWrapper",
    "matcher": "${scratch.matcher}",
    "o2m_weight": 2.0,
    "o2m_matcher": {"_target_": "sam3.train.matcher.BinaryOneToManyMatcher", "alpha": 0.3, "threshold": 0.4, "topk": 4},
    "use_o2m_matcher_on_o2m_aux": False,
    "loss_fns_find": [
        {"_target_": "sam3.train.loss.loss_fns.Boxes", "weight_dict": {"loss_bbox": 5.0, "loss_giou": 2.0}},
        {"_target_": "sam3.train.loss.loss_fns.IABCEMdetr", "weak_loss": False,
         "weight_dict": {"loss_ce": 20.0, "presence_loss": 20.0}, "pos_weight": 10.0, "alpha": 0.25, "gamma": 2,
         "use_presence": True, "pos_focal": False, "pad_n_queries": 200, "pad_scale_pos": 1.0},
        {"_target_": "sam3.train.loss.loss_fns.Masks", "focal_alpha": 0.25, "focal_gamma": 2.0,
         "weight_dict": {"loss_mask": 200.0, "loss_dice": 10.0}, "compute_aux": False},
    ],
    "loss_fn_semantic_seg": None,
    "scale_by_find_batch_size": "${scratch.scale_by_find_batch_size}",
}


def _write_config(epochs: int, run: str, lr_scale: float) -> str:
    from omegaconf import OmegaConf
    cfg_dir = "/opt/sam3/sam3/train/configs"
    cfg = OmegaConf.load(f"{cfg_dir}/roboflow_v100/roboflow_v100_full_ft_100_images.yaml")
    cfg.paths.roboflow_vl_100_root = f"{VOL}/data"
    cfg.paths.experiment_log_dir = f"{VOL}/runs/{run}"
    cfg.paths.bpe_path = "/opt/sam3/sam3/assets/bpe_simple_vocab_16e6.txt.gz"
    cfg.roboflow_train.supercategory = "rust"
    cfg.roboflow_train.num_images = None
    cfg.roboflow_train.loss = OmegaConf.create(SEG_LOSS)
    cfg.scratch.enable_segmentation = True
    cfg.scratch.lr_scale = lr_scale
    cfg.scratch.num_train_workers = 4
    cfg.trainer.max_epochs = epochs
    cfg.trainer.val_epoch_freq = epochs
    cfg.trainer.skip_saving_ckpts = False
    cfg.launcher.gpus_per_node = 1
    cfg.submitit.use_cluster = False
    os.makedirs(f"{cfg_dir}/walkdown", exist_ok=True)
    OmegaConf.save(cfg, f"{cfg_dir}/walkdown/walkdown_ft.yaml")
    return "configs/walkdown/walkdown_ft.yaml"


def _save(name: str, result: dict) -> dict:
    os.makedirs(f"{VOL}/results", exist_ok=True)
    with open(f"{VOL}/results/{name}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    volume.commit()
    return result


@app.function(image=image, gpu="H100", volumes={VOL: volume}, secrets=[hf_secret], timeout=3 * 3600, retries=0,
              max_containers=1)  # $11.85 max per run
def train_run(epochs: int, run: str, lr_scale: float = 0.1) -> dict:
    t0 = time.time()
    config = _write_config(epochs, run, lr_scale)
    proc = subprocess.run(["python", "sam3/train/train.py", "-c", config, "--use-cluster", "0", "--num-gpus", "1"],
                          cwd="/opt/sam3", capture_output=True, text=True)
    volume.commit()
    ckpts = []
    for dp, _, fs in os.walk(f"{VOL}/runs/{run}"):
        ckpts += [os.path.join(dp, f) for f in fs if f.endswith((".pt", ".pth"))]
    wall = time.time() - t0
    return _save(f"train_{run}", dict(run=run, epochs=epochs, lr_scale=lr_scale, returncode=proc.returncode,
                                      stdout_tail=proc.stdout[-3000:], stderr_tail=proc.stderr[-6000:],
                                      checkpoints=ckpts, wall_s=round(wall), usd_estimate=round(wall * H100_PER_SECOND, 2)))


@app.function(image=image, gpu="H100", volumes={VOL: volume}, secrets=[hf_secret], timeout=3600, retries=0,
              max_containers=1)
def eval_run(tag: str, checkpoint: str = "", threshold: float = 0.5) -> dict:
    """Text prompt "rust" on the dev images (test folder) with base SAM 3 or a fine-tuned checkpoint."""
    import numpy as np
    import torch
    from PIL import Image
    from pycocotools import mask as mask_utils
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model
    t0 = time.time()
    model = build_sam3_image_model(bpe_path="/opt/sam3/sam3/assets/bpe_simple_vocab_16e6.txt.gz")
    if checkpoint:
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        state = state.get("model", state)
        missing, unexpected = model.load_state_dict(state, strict=False)
        load_info = dict(missing=len(missing), unexpected=len(unexpected))
    else:
        load_info = None
    proc = Sam3Processor(model, confidence_threshold=threshold)
    coco = json.load(open(f"{VOL}/data/rust/test/_annotations.coco.json"))
    out = {}
    with torch.autocast("cuda", dtype=torch.bfloat16):
        for im in coco["images"]:
            img = Image.open(f"{VOL}/data/rust/test/{im['file_name']}").convert("RGB")
            state = proc.set_image(img)
            state = proc.set_text_prompt(prompt="rust", state=state)
            recs = []
            for m, s in zip(state["masks"], state["scores"]):
                arr = np.asfortranarray(m.squeeze().cpu().numpy().astype(np.uint8))
                rle = mask_utils.encode(arr)
                rle["counts"] = rle["counts"].decode()
                recs.append(dict(score=float(s), rle=rle))
            out[im["file_name"]] = recs
    return _save(f"eval_{tag}", dict(tag=tag, checkpoint=checkpoint, threshold=threshold, load=load_info, results=out,
                                     wall_s=round(time.time() - t0), usd_estimate=round((time.time() - t0) * H100_PER_SECOND, 2)))


@app.local_entrypoint()
def train(epochs: int = 1, run: str = "smoke", lr_scale: float = 0.1) -> None:
    r = train_run.remote(epochs, run, lr_scale)
    print(json.dumps({k: v for k, v in r.items() if k not in ("stdout_tail",)})[:8000])


@app.local_entrypoint()
def evaluate(tag: str = "base", checkpoint: str = "", threshold: float = 0.5) -> None:
    r = eval_run.remote(tag, checkpoint, threshold)
    print(json.dumps({k: v for k, v in r.items() if k != "results"}))
