"""Muse Glimmer 30B verifier on the Fireworks Serverless Training API, with images (no dataset upload, no deployment).

The cookbook's "Muse Glimmer First Fine-Tune" recipe (examples/sft/muse_glimmer_starter.py) is text-only: its
renderer has no image processor and its datum/report code calls ``to_ints()``, which rejects image chunks. The
Serverless Training API itself accepts image datums, so this script uses the recipe's calls (LoRA training client,
``forward_backward(..., "cross_entropy")``, ``optim_step`` with Adam, ``save_weights_for_sampler``, sampling client)
with the cookbook's image-enabled Muse Glimmer renderer and ``datum_from_model_input_weights``.

Same data and settings as the Modal run (docs/GLIMMER_PLAN.md, RESULTS 14): the balanced training file from
``benchmark.glimmer_data`` (teacher labels on the clean train pool + FLUX-train look-alike rejections; never test
images, hosted Muse Spark outputs, Muse Image or public negatives), LoRA r=16 alpha=32 on attention, MLP and
unembedding, lr 1e-4, batch 16, 2 epochs, "Reasoning strength: low". LoRA SFT on Glimmer is promotional $0 until
Nov 30; sampling for the evaluation is billed (Serverless Training rates: $1.96 / 1M prefill, $4.88 / 1M sampled).

Evaluation: the tuned snapshot answers the audit (133) and real public negatives (185) rows of the Glimmer
evaluation file; replies go to WALKDOWN_DATA_DIR/glimmer/results/eval_fw-tuned.jsonl in the format scored by
``benchmark.glimmer_eval_score``.

Runs in the Fireworks training venv, from the cookbook's ``training/`` folder:

    PYTHONPATH=<cookbook>;<cookbook>/training G:\\walkdown-data\\venv-fwtrain\\Scripts\\python.exe <repo>/benchmark/fw_glimmer_train.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

DATA = Path(os.environ.get("WALKDOWN_DATA_DIR", "G:/walkdown-data")) / "glimmer"
BASE_MODEL = "accounts/fireworks/models/muse-glimmer-30b"
TOKENIZER_MODEL = "meta-models/Muse-Glimmer-30B"
PREFILL_PER_M, SAMPLE_PER_M = 1.96, 4.88
CHECKPOINT_EVERY = 20
REASONING = "Reasoning strength: low\n\n"


def chat(ex: dict, with_answer: bool) -> list[dict]:
    """Production verifier request -> cookbook chat messages (image parts carry the data URL)."""
    msgs = []
    for m in ex["messages"]:
        if isinstance(m["content"], str):
            text = (REASONING if m["role"] == "system" else "") + m["content"]
            msgs.append({"role": m["role"], "content": text})
            continue
        parts = [{"type": "text", "text": p["text"]} if p["type"] == "text" else {"type": "image", "image": p["image_url"]["url"]}
                 for p in m["content"]]
        msgs.append({"role": m["role"], "content": parts})
    if with_answer:
        msgs.append({"role": "assistant", "content": ex["target"]})
    return msgs


def decide(text: str) -> bool | None:
    s, e = text.find("{"), text.rfind("}")
    try:
        return bool(json.loads(text[s:e + 1])["is_defect"])
    except Exception:  # noqa: BLE001
        return None


def read(name: str, sets: set[str] | None = None, n: int | None = None) -> list[dict]:
    rows = []
    with (DATA / "data" / f"{name}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if sets is None or e.get("set") in sets:
                rows.append(e)
            if n and len(rows) >= n:
                break
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="1 step on 4 examples, sample 2 eval rows")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--max-eval-usd", type=float, default=2.0)
    args = ap.parse_args()

    if sys.platform == "win32" and "resource" not in sys.modules:  # cookbook memory tracer imports the Unix-only module
        import types
        stub = types.ModuleType("resource")
        stub.RUSAGE_SELF = 0
        stub.getrusage = lambda *_: types.SimpleNamespace(ru_maxrss=0)
        sys.modules["resource"] = stub
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    from fireworks.training import sdk
    from fireworks.training.sdk import FiretitanServiceClient
    from training.renderer import TrainOnWhat, get_renderer, get_text_content
    from training.renderer._supervised import datum_from_model_input_weights
    from training.renderer.muse_glimmer import MuseGlimmerImageTokenCounter
    from training.renderer.tokenizer import get_tokenizer
    from training.utils.serverless import enable_serverless_supervised_409_retry, serverless_base_url

    tokenizer = get_tokenizer(TOKENIZER_MODEL)
    renderer = get_renderer("muse_glimmer", tokenizer, image_processor=MuseGlimmerImageTokenCounter.from_pretrained(TOKENIZER_MODEL))
    train = read("train", n=4 if args.dry_run else None)
    evals = read("eval", {"audit", "public"})[: 2 if args.dry_run else None]
    out_dir = DATA / "fw"
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (out_dir / ("dry_run.jsonl" if args.dry_run else "train_log.jsonl")).open("a", encoding="utf-8")

    def datum(ex: dict):
        mi, w = renderer.build_supervised_example(chat(ex, True), train_on_what=TrainOnWhat.LAST_ASSISTANT_TURN)
        return datum_from_model_input_weights(mi, w, max_length=4096)

    t0 = time.time()
    datums = [datum(ex) for ex in train]
    print(f"rendered {len(datums)} train datums in {time.time() - t0:.0f} s", flush=True)

    service = FiretitanServiceClient(api_key=os.environ["FIREWORKS_API_KEY"],
                                     base_url=serverless_base_url(os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai")))
    enable_serverless_supervised_409_retry(service)
    try:
        return _run(args, service, sdk, renderer, tokenizer, datums, evals, out_dir, log, get_text_content)
    finally:  # serverless allows one concurrent Glimmer training run per account: always release the session
        try:  # close() alone keeps the run slot busy; deleting the session releases it (sampler snapshots persist)
            service.delete_training_session()
        except Exception as err:  # noqa: BLE001
            print(f"session delete failed: {err}", flush=True)
        try:
            service.close()
        except Exception as err:  # noqa: BLE001
            print(f"session close failed: {err}", flush=True)


def _run(args, service, sdk, renderer, tokenizer, datums, evals, out_dir, log, get_text_content) -> int:
    # Resume: training state (weights + optimizer) is saved every CHECKPOINT_EVERY steps; a restart continues there.
    state_file = out_dir / "checkpoint.json"
    resume = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() and not args.dry_run else None
    def create():
        if resume:
            return service.create_training_client_from_state_with_optimizer(resume["path"])
        return service.create_lora_training_client(base_model=BASE_MODEL, rank=16, alpha=32, train_mlp=True,
                                                   train_attn=True, train_unembed=True)

    for attempt in range(30):  # one concurrent Glimmer run per account: wait for a stale session to be released
        try:
            client = create()
            break
        except Exception as err:  # noqa: BLE001
            if "maximum concurrent serverless training runs" not in str(err) or attempt == 29:
                raise
            print("training slot busy (stale session); retrying in 60 s", flush=True)
            time.sleep(60)
    if resume:
        print(f"resumed from step {resume['step']}: {resume['path']}", flush=True)
    adam = sdk.AdamParams(learning_rate=args.lr, beta1=0.9, beta2=0.999, eps=1e-8, weight_decay=0.0, grad_clip_norm=1.0)
    rng = random.Random(20261031)
    step, t1 = 0, time.time()
    done_steps = resume["step"] if resume else 0
    for epoch in range(1 if args.dry_run else args.epochs):
        order = list(range(len(datums)))
        rng.shuffle(order)  # same seeded order on every run, so resumed steps line up
        for s in range(0, len(order), args.batch_size):
            if step < done_steps:
                step += 1
                continue
            batch = [datums[i] for i in order[s:s + args.batch_size]]
            fb = client.forward_backward(batch, "cross_entropy").result()
            client.optim_step(adam).result()
            step += 1
            if not args.dry_run and step % CHECKPOINT_EVERY == 0:
                path = client.save_state(f"walkdown-glimmer-fw-step{step}").result().path
                state_file.write_text(json.dumps(dict(step=step, path=path)), encoding="utf-8")
            m = dict(getattr(fb, "metrics", None) or {})
            loss = m.get("loss:sum", 0.0) / max(float(m.get("response_tokens") or 1.0), 1.0)
            row = dict(step=step, epoch=epoch + 1, loss=round(loss, 4), elapsed_s=round(time.time() - t1))
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(json.dumps(row), flush=True)

    snapshot = client.save_weights_for_sampler("walkdown-glimmer-fw-v1").result().path
    sampler = service.create_sampling_client(model_path=snapshot, tokenizer=tokenizer)
    params = sdk.SamplingParams(max_tokens=1200, temperature=0.0, stop=renderer.get_stop_sequences())
    replies = (out_dir.parent / "results" / ("eval_fw-dry.jsonl" if args.dry_run else "eval_fw-tuned.jsonl")).open("w", encoding="utf-8")
    prefill = sampled = 0
    for i in range(0, len(evals), 16):
        if (prefill * PREFILL_PER_M + sampled * SAMPLE_PER_M) / 1e6 > args.max_eval_usd:
            print("eval sampling budget reached", flush=True)
            break
        chunk = evals[i:i + 16]
        prompts = [renderer.build_generation_prompt(chat(ex, False)) for ex in chunk]
        futs = []
        for ex, p in zip(chunk, prompts):
            # The sampler takes text tokens only: one placeholder token per image, images passed as data URLs.
            urls = [part["image_url"]["url"] for m in ex["messages"] if not isinstance(m["content"], str)
                    for part in m["content"] if part["type"] == "image_url"]
            chunks = [sdk.types.EncodedTextChunk(tokens=[renderer.image_placeholder_token_id])
                      if isinstance(c, sdk.types.ImageChunk) else c for c in p.chunks]
            futs.append(sampler.sample(prompt=sdk.ModelInput(chunks=chunks), num_samples=1, sampling_params=params,
                                       images=urls))
        for ex, p, fut in zip(chunk, prompts, futs):
            res = fut.result() if hasattr(fut, "result") else fut
            toks = list(res.sequences[0].tokens)
            prefill += p.length
            sampled += len(toks)
            msg, _ = renderer.parse_response(toks)
            text = get_text_content(msg)
            replies.write(json.dumps(dict(id=ex["id"], set=ex["set"], accept=decide(text), text=text[-600:])) + "\n")
        replies.flush()
        print(f"eval {min(i + 16, len(evals))}/{len(evals)}, ${(prefill * PREFILL_PER_M + sampled * SAMPLE_PER_M) / 1e6:.2f}", flush=True)
    summary = dict(steps=step, train_examples=len(datums), train_s=round(time.time() - t1), snapshot=snapshot,
                   eval_rows=len(evals), prefill_tokens=prefill, sampled_tokens=sampled,
                   eval_usd=round((prefill * PREFILL_PER_M + sampled * SAMPLE_PER_M) / 1e6, 3), training_usd="0 (promotional LoRA SFT)")
    log.write(json.dumps(dict(summary=summary)) + "\n")
    print(json.dumps(summary), flush=True)
    close = getattr(sampler, "close", None)
    if callable(close):
        close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
