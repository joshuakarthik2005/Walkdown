# Muse Glimmer verifier distillation on Modal: plan and cost (awaiting builder OK)

**Status:** plan only. Nothing is trained until the builder says OK. Fireworks cannot train it: dataset uploads are disabled platform-wide, with no ETA (Fireworks support, 2026-10-28).

## Goal

Distil the Walkdown verifier (accept or reject a SAM candidate, plus a severity grade) into **Muse Glimmer 30B**, a small open-weights model.

- **Success:** On-prem verification on one GPU, cheaper and faster than Muse Spark Open, with no measured loss.
- **Failure:** the tuned model loses accuracy. That is reported as a negative result.

## Model

- `meta-models/Muse-Glimmer-30B`, Apache 2.0, plus the Muse Glimmer Usage Policy.
- Dense, 29.6B parameters including a 1.8B vision encoder. Image + text input.
- About 60 GB in BF16. Needs transformers 5.15 (dev) for `MuseGlimmerForConditionalGeneration`.
- The model card's sampling settings are temperature 1.0, top_p 0.95, top_k 64. Reasoning strength is set in the system prompt (`Reasoning strength: low`).
- **Fine-tuned weights are never published.** They stay in a private Modal volume. If the builder approves the Fireworks evaluation, they also go to a private Fireworks model in the builder's account; that is not public.

## Training data: open-weights outputs only, training images only

| Source | Count | Role |
|---|---|---|
| Teacher labels: SAM 3.1 open-weights candidates on the 585-image clean train pool, graded by Muse Spark Open (Baseten) | 1,298 candidates (final counts in `benchmark/results/teacher_labels_train_pool.json`) | Main set |
| F6 synthetic hard negatives (clearly labelled synthetic; training only) | 200–400 planned | Balance: the teacher accepts about 92% of pool candidates |
| Public negatives sets (item 3a; rights-cleared) | Only images kept out of every FP test set | Balance |

- **Never used for training:** hosted Muse Spark, hosted SAM 3.1 or Muse Wonder outputs (Meta Model API terms 10.1(ix)); any dev or test image; the human audit labels (test split).
- **Format:** the verifier's exact production prompt with its two images (crop with the mask outlined, plus the full frame). The target is the teacher's grade JSON only, not its reasoning text.
- **Split:** 10% of the pool's source clusters are held out for early stopping.

## Recipe

- **Method:** QLoRA. The language model is in 4-bit NF4 (about 17 GB, per the model card's quantised footprint). LoRA r = 16, alpha = 32, on attention and MLP projections. The vision encoder and projector stay frozen.
- **Settings:** BF16 compute, gradient checkpointing, sequence length ≤ 4,096, effective batch 16, LR 1e-4 cosine, 2 epochs.
- **GPU:** 1 × H100 80 GB on Modal ($3.95/h). An A100 80 GB ($2.50/h) is the fallback if H100 capacity is short.
- **Stages, each stopped and reported before the next:**
  1. **Weights to a private Modal volume.** CPU container with the builder's HF token; it downloads only if the repo terms allow.
  2. **Smoke test.** Load the model, run 20 held-out pool examples zero-shot, run 10 training steps. Check the loss falls and the output parses.
  3. **Full training run.**

## Evaluation (no training example in any evaluation set)

1. **Agreement with the teacher on held-out pool clusters:** decision agreement, and severity exact and within ±1.
2. **Test split, all 5,066 text-prompt candidates:** the same statistics as RESULTS §6 (TP retention, invalid-reply rate, agreement with Muse Spark Open and with hosted Muse Spark, latency, cost per candidate). Zero-shot Glimmer is the baseline.
3. **Human audit (RESULTS §8, n = 89 sure labels):** precision, recall and accuracy with 95% CIs, next to the other verifiers.
4. **False alarms on negatives:** builder footage and public negatives, kept separate from any training negatives.

**Where it runs:** served on Modal (vLLM if it supports the architecture, otherwise transformers with batching). Alternatively, with the builder's OK, the LoRA is uploaded to the builder's Fireworks account and both the base and tuned models are evaluated on one on-demand deployment. LoRA model uploads are still allowed: a probe created an adapter resource, got a signed upload URL and was deleted.

## Cost (Modal list prices, 2026-10-28)

| Stage | Estimate | Cap |
|---|---|---|
| Weights to volume (CPU, about 60 GB) | ≈ $0.3 | $1 |
| Smoke test (H100, ≤ 20 min) | ≈ $1.3 | $2 |
| Training: ≈ 1,700 examples × about 2.5k tokens × 2 epochs ≈ 8.5M tokens. At an assumed 1–2k tokens/s for QLoRA on one H100, that is 1.2–2.4 h | ≈ $5–10 | **$15** (hard stop, job killed) |
| Evaluation on Modal (5,066 + 89 + held-out candidates, base and tuned) | ≈ $6–12 | $15 |
| **Modal total** | **≈ $13–24** | $33 (pool used ≈ $0.7 of ≈ $80; stop $90) |

- **Throughput is an assumption.** The smoke test measures it, and the training estimate is re-reported before stage 3.
- **Every Modal job runs alone:** `max_containers=1`, `retries=0`. Containers are checked to be at zero afterwards, and spend is logged in COST_LOG.
- **Alternative evaluation on Fireworks:** one H200 on-demand deployment at $8/h, minimum replicas 0, deleted in `finally`, 2 h cap ≈ $16. It evaluates base and tuned Glimmer in the same window (multi-LoRA).

## Decision needed from the builder

1. OK to start stage 1 (weights) and stage 2 (smoke test), about $2.
2. Stage 3 waits for a second OK, with the measured throughput.
