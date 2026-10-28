"""One-request probe: does Fireworks serverless LoRA training accept an image datum for Muse Glimmer 30B?

No dataset upload is involved: the Serverless Training API takes datums directly in ``forward_backward``. This
sends ONE datum (a train-pool candidate crop plus its Muse Spark Open teacher grade, i.e. open-weights data
allowed for training) and runs one forward/backward pass. There is no optimizer step and nothing is saved.

Runs in the separate training venv on G: (the ``fireworks-ai[training]`` extra pins pydantic < 2.13 and pulls in
torch, so it is kept out of the project venv; see requirements-fireworks-training.txt):

    G:\\walkdown-data\\venv-fwtrain\\Scripts\\python.exe benchmark\\fireworks_train_probe.py
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("WALKDOWN_DATA_DIR", "G:/walkdown-data"))
os.environ.setdefault("HF_HOME", "G:/walkdown-cache/hf")  # processor/tokenizer configs only; never on C:
BASE = "accounts/fireworks/models/muse-glimmer-30b"
HF_REPO = "meta-models/Muse-Glimmer-30B"


def first_teacher_example() -> tuple[bytes, str]:
    """A train-pool image (full frame, JPEG bytes) and the teacher's grade JSON for one of its candidates."""
    for line in (DATA / "runs" / "teacher_train_pool_journal.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for row in r["rows"]:
            if row["grade"]:
                from PIL import Image
                img = Image.open(DATA / "corrosion-segmentation-xybsj" / r["image"]).convert("RGB")
                img.thumbnail((448, 448))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                return buf.getvalue(), json.dumps(row["grade"])
    raise SystemExit("no teacher label found")


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    from transformers import AutoProcessor

    from fireworks.training import tinker as fw
    from fireworks.training.sdk.types.image_chunk import ImageChunk

    jpg, target = first_teacher_example()
    proc = AutoProcessor.from_pretrained(HF_REPO, token=os.environ.get("HF_TOKEN"))
    messages = [{"role": "user", "content": [{"type": "image"},
                                             {"type": "text", "text": "Is the outlined region rust? Reply in JSON."}]},
                {"role": "assistant", "content": [{"type": "text", "text": target}]}]
    from PIL import Image
    enc = proc(text=proc.apply_chat_template(messages, tokenize=False), images=[Image.open(io.BytesIO(jpg))],
               return_tensors=None)
    ids = list(enc["input_ids"][0])
    image_id = proc.tokenizer.convert_tokens_to_ids(proc.image_token) if hasattr(proc, "image_token") else 200092
    img_pos = [i for i, t in enumerate(ids) if t == image_id]
    if not img_pos:
        raise SystemExit("no image tokens in the rendered prompt")
    a, b = img_pos[0], img_pos[-1] + 1
    n_img = b - a
    target_ids = proc.tokenizer(target, add_special_tokens=False)["input_ids"]
    # Loss only on the assistant's answer: the last len(target_ids) (+ end-of-turn) tokens.
    answer_start = len(ids) - len(target_ids) - 1
    chunks = [fw.EncodedTextChunk(tokens=ids[:a]), ImageChunk(data=jpg, format="jpeg", expected_tokens=n_img),
              fw.EncodedTextChunk(tokens=ids[b:-1])]
    targets = ids[1:]
    weights = [1.0 if i + 1 >= answer_start else 0.0 for i in range(len(ids) - 1)]
    datum = fw.Datum(model_input=fw.ModelInput(chunks=chunks),
                     loss_fn_inputs={"target_tokens": targets, "weights": weights})

    service = fw.ServiceClient(api_key=os.environ["FIREWORKS_API_KEY"])
    client = service.create_lora_training_client(base_model=BASE, rank=8)
    try:
        out = client.forward_backward([datum], "cross_entropy").result()
        m = out.metrics
        print(json.dumps(dict(ok=True, tokens=len(ids), image_tokens=n_img, answer_tokens=len(target_ids),
                              metrics={k: float(v) for k, v in m.items()})))
    except Exception as err:  # noqa: BLE001  the probe's answer is the error itself
        print(json.dumps(dict(ok=False, error=f"{type(err).__name__}: {str(err)[:600]}", tokens=len(ids),
                              image_tokens=n_img)))
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
