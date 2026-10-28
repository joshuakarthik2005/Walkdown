"""SAM 3.1 open weights on Modal (Walkdown "On-prem" mode and video tracking).

Runs the official SAM 3.1 Object Multiplex predictor (github.com/facebookresearch/sam3, pinned commit) on one
L40S GPU. The checkpoint (gated: facebook/sam3.1, SAM License) is downloaded once into a private Modal Volume
with the builder's HF token; weights never leave Modal and are never published.

The container scales to zero (``scaledown_window``), so idle time is not billed. Single images are run as a
one-frame "video" (the multiplex predictor is a video predictor); clips are tracked across frames.

    .venv\\Scripts\\python.exe -m modal run modal_apps/sam_open.py::probe --image <path.jpg>
    .venv\\Scripts\\python.exe -m modal deploy modal_apps/sam_open.py
"""

from __future__ import annotations

import os

import modal

SAM3_COMMIT = "f1647e8d0c1d280991f4d1b7d974c2704537fe66"
IMAGE_NEW_DET_THRESH = 0.5  # single images; the multiplex video builder uses 0.65 for new tracks
BOX_MATCH_IOU = 0.3  # a box exemplar's detection must overlap the proposed box this much
WEIGHTS = "/weights"
CHECKPOINT = f"{WEIGHTS}/sam3.1_multiplex.pt"

app = modal.App("walkdown-sam31")
weights = modal.Volume.from_name("walkdown-sam31-weights", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .pip_install("torch==2.10.0", "torchvision", index_url="https://download.pytorch.org/whl/cu128")
    .run_commands(f"git clone https://github.com/facebookresearch/sam3.git /opt/sam3 && cd /opt/sam3 "
                  f"&& git checkout {SAM3_COMMIT} && pip install -e .")
    # psutil, decord and scipy are imported by sam3's video predictor but not listed in its pyproject.
    .pip_install("huggingface_hub", "opencv-python-headless<4.12", "pycocotools", "numpy<2", "pillow", "einops",
                 "psutil", "decord", "scipy", "scikit-image")
)


def _load_env() -> None:
    if modal.is_local():
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)


# The HF token is read from the local .env at deploy/run time and passed as a Modal secret; never printed.
_load_env()
hf_secret = modal.Secret.from_dict({"HF_TOKEN": os.environ.get("HF_TOKEN", "")})


@app.cls(image=image, gpu="L40S", volumes={WEIGHTS: weights}, secrets=[hf_secret], scaledown_window=120, retries=0,
         timeout=1800, max_containers=1)
class Sam31:
    @modal.enter()
    def load(self) -> None:
        import shutil

        from huggingface_hub import hf_hub_download
        if not os.path.exists(CHECKPOINT):
            for name in ("sam3.1_multiplex.pt", "config.json"):
                path = hf_hub_download("facebook/sam3.1", name, token=os.environ["HF_TOKEN"])
                shutil.copy(path, f"{WEIGHTS}/{name}")
            weights.commit()
        from sam3.model_builder import build_sam3_multiplex_video_predictor
        self.predictor = build_sam3_multiplex_video_predictor(checkpoint_path=CHECKPOINT, use_fa3=False)
        # Upstream mismatch at the pinned commit: the base predictor's start_session passes offload_state_to_cpu
        # (and possibly video_loader_type) to the multiplex model's init_state, which does not accept them.
        # Drop keyword arguments init_state does not declare.
        import functools
        import inspect
        init = self.predictor.model.init_state
        accepted = set(inspect.signature(init).parameters)

        @functools.wraps(init)
        def init_state(**kwargs):
            return init(**{k: v for k, v in kwargs.items() if k in accepted})
        self.predictor.model.init_state = init_state

    def _track(self, frames: list[bytes], prompt: str | None, propagate: bool,
               boxes: list[list[float]] | None = None) -> dict:
        """Run a text prompt and/or box exemplars (relative xywh) on frame 0 and (optionally) propagate;
        returns per-frame raw outputs."""
        import tempfile

        out: dict[int, dict] = {}
        with tempfile.TemporaryDirectory() as d:
            for i, jpg in enumerate(frames):
                with open(os.path.join(d, f"{i}.jpg"), "wb") as f:
                    f.write(jpg)
            sid = self.predictor.handle_request(dict(type="start_session", resource_path=d))["session_id"]
            try:
                req = dict(type="add_prompt", session_id=sid, frame_index=0, text=prompt)
                if boxes:
                    req.update(bounding_boxes=boxes, bounding_box_labels=[1] * len(boxes))
                resp = self.predictor.handle_request(req)
                out[0] = resp["outputs"]
                if propagate and len(frames) > 1:
                    for r in self.predictor.handle_stream_request(dict(type="propagate_in_video", session_id=sid)):
                        out[r["frame_index"]] = r["outputs"]
            finally:
                self.predictor.handle_request(dict(type="close_session", session_id=sid))
        return out

    @modal.method()
    def segment_boxes(self, images: list[bytes], boxes: list[list[list[float]]],
                      text: str | None = None) -> list[list[dict]]:
        """Per image, one mask per proposed box (pixel xyxy), as COCO RLE with the box index as object id.

        The open-weights multiplex model has no per-object box prompt (points are not accepted and boxes are
        visual exemplars of a concept). Each image's boxes are therefore given together as positive exemplars
        (with ``text`` if set), and each box keeps the detection that overlaps it most (``match_boxes``).
        """
        import cv2
        import numpy as np
        model = self.predictor.model
        video_thresh, model.new_det_thresh = model.new_det_thresh, IMAGE_NEW_DET_THRESH
        out = []
        try:
            for jpg, bxs in zip(images, boxes):
                if not bxs:
                    out.append([])
                    continue
                h, w = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR).shape[:2]
                rel = [[l / w, t / h, (r - l) / w, (b - t) / h] for l, t, r, b in bxs]
                raw = self._track([jpg], text, propagate=False, boxes=rel)[0]
                out.append(match_boxes(self._encode(0, raw), [list(map(float, b)) for b in bxs]))
        finally:
            model.new_det_thresh = video_thresh
        return out

    @modal.method()
    def describe(self, jpg: bytes, prompt: str = "rust") -> dict:
        """Keys, types and shapes of the raw outputs (to write the parser against the real format)."""
        import numpy as np
        raw = self._track([jpg], prompt, propagate=False)[0]

        def info(v):
            if hasattr(v, "shape"):
                return f"{type(v).__name__} {tuple(v.shape)} {getattr(v, 'dtype', '')}"
            if isinstance(v, (list, tuple)):
                return f"{type(v).__name__} len {len(v)}" + (f" first {info(v[0])}" if v else "")
            if isinstance(v, dict):
                return {k: info(x) for k, x in v.items()}
            return f"{type(v).__name__} {str(v)[:80]}"
        return info(raw) if isinstance(raw, dict) else {"type": info(raw)}

    @staticmethod
    def _encode(f: int, o: dict) -> list[dict]:
        import numpy as np
        from pycocotools import mask as mask_utils
        ids, probs = o["out_obj_ids"], o["out_probs"]
        masks, boxes = o["out_binary_masks"], o["out_boxes_xywh"]
        h, w = masks.shape[-2:] if len(masks) else (0, 0)
        result = []
        for k in range(len(ids)):
            m = np.asfortranarray(np.asarray(masks[k]).astype(np.uint8))
            rle = mask_utils.encode(m)
            rle["counts"] = rle["counts"].decode()
            x, y, bw, bh = (float(v) for v in boxes[k])
            if max(x, y, bw, bh) <= 1.0:  # relative coordinates
                x, y, bw, bh = x * w, y * h, bw * w, bh * h
            result.append(dict(frame=int(f), obj_id=int(ids[k]), score=float(probs[k]),
                               box_xyxy=[x, y, x + bw, y + bh], rle=rle))
        return result

    @modal.method()
    def segment_images(self, images: list[bytes], prompt: str = "rust") -> list[list[dict]]:
        """Independent images (one session each): instances per image as COCO RLE.

        Single images use a new-detection threshold of IMAGE_NEW_DET_THRESH (0.5) instead of the video builder's
        0.65: there is no track to confirm, and 0.5 matches the lowest score the hosted SAM 3.1 returns.
        """
        model = self.predictor.model
        video_thresh, model.new_det_thresh = model.new_det_thresh, IMAGE_NEW_DET_THRESH
        try:
            return [self._encode(0, self._track([jpg], prompt, propagate=False)[0]) for jpg in images]
        finally:
            model.new_det_thresh = video_thresh

    @modal.method()
    def segment(self, frames: list[bytes], prompt: str = "rust", propagate: bool = True) -> list[dict]:
        """Instances per frame as COCO RLE: [{frame, obj_id, score, box_xyxy, rle}]."""
        result = []
        for f, o in self._track(frames, prompt, propagate).items():
            result += self._encode(f, o)
        return result


def _box_iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / union if union > 0 else 0.0


def match_boxes(records: list[dict], boxes: list[list[float]], min_iou: float = BOX_MATCH_IOU) -> list[dict]:
    """One record per proposed box: the unused detection whose box overlaps it most (box IoU >= min_iou),
    relabelled with the box index as its object id. Boxes without a match get no mask."""
    pairs = sorted(((_box_iou(r["box_xyxy"], b), i, k) for i, r in enumerate(records) for k, b in enumerate(boxes)),
                   reverse=True)
    used_r, used_b, out = set(), set(), []
    for iou, i, k in pairs:
        if iou < min_iou:
            break
        if i in used_r or k in used_b:
            continue
        used_r.add(i)
        used_b.add(k)
        out.append({**records[i], "obj_id": k, "box_iou": round(iou, 3)})
    return sorted(out, key=lambda r: r["obj_id"])


@app.function(image=image, timeout=600)
def check_imports() -> str:
    """CPU-only import check of the predictor module (avoids crash-looping a GPU container on a missing dep)."""
    from sam3.model_builder import build_sam3_multiplex_video_predictor  # noqa: F401
    return "sam3 imports OK"


@app.local_entrypoint()
def imports() -> None:
    print(check_imports.remote())


@app.local_entrypoint()
def probe_boxes(image: str, boxes: str, text: str = "") -> None:
    """boxes: JSON list of pixel [left, top, right, bottom]."""
    import json
    with open(image, "rb") as f:
        jpg = f.read()
    recs = Sam31().segment_boxes.remote([jpg], [json.loads(boxes)], text or None)[0]
    print(json.dumps([{k: v for k, v in r.items() if k != "rle"} for r in recs]))


@app.local_entrypoint()
def probe(image: str, prompt: str = "rust") -> None:
    with open(image, "rb") as f:
        jpg = f.read()
    print(Sam31().describe.remote(jpg, prompt))
