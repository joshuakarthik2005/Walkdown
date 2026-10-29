# API cost log

Estimated from the `usage` fields returned by each call, using official prices:
- `muse-spark-1.3`: $1.25 / 1M input, $0.15 / 1M cached input, $4.25 / 1M output (reasoning tokens billed as output)
- `sam-3.1`: $2.50 / 1,000 images; video $0.20 / 1,000 frames, minimum 50 frames per request

Budget: target $50–70 Meta spend, hard stop $120.

| Date | Job | Model | Items | Input tokens | Output tokens | Est. $ | Running total $ |
|---|---|---|---|---|---|---|---|
| 2026-10-27 | Smoke test, run 1 (no reasoning effort set; reply empty, 200-token cap used up by reasoning) | muse-spark-1.3 | 1 | 17 | 200 | 0.000871 | 0.000871 |
| 2026-10-27 | Smoke test, run 2 (`reasoning.effort=minimal`) | muse-spark-1.3 | 1 | 17 | 75 (61 reasoning) | 0.000340 | 0.001211 |
| 2026-10-27 | SAM probe: 1 dev image, prompt "rust" (format check) | sam-3.1 | 1 image | – | – | 0.0025 | 0.0037 |
| 2026-10-27 | SAM fixtures, run 1: synthetic plate image + 6-frame clip, prompt "rust" (both empty) | sam-3.1 | 1 image + 50 frames billed | – | – | 0.0125 | 0.0162 |
| 2026-10-27 | SAM fixtures, run 2: same media, prompt "circle" (image 2 found, video empty) | sam-3.1 | 1 image + 50 frames billed | – | – | 0.0125 | 0.0287 |
| 2026-10-27 | SAM video debug probes, mp4v then H.264 (both empty) | sam-3.1 | 2 × 50 frames billed | – | – | 0.0200 | 0.0487 |
| 2026-10-27 | SAM dry run, dev split, prompts "rust", "corrosion", "corroded metal" | sam-3.1 | 150 images | – | – | 0.3750 | 0.4237 |
| 2026-10-27 | Verifier dry run, dev, 50 candidates, reasoning low | muse-spark-1.3 | 50 | 49,532 (30,625 cached) | 43,690 (37,174 reasoning) | 0.2139 | 0.6376 |
| 2026-10-27 | Verifier consistency repeat, dev, 30 candidates | muse-spark-1.3 | 30 | – | – | 0.1310 | 0.7686 |
| 2026-10-27 | Verifier dry run on Baseten Muse Spark Open, same 50 + 30 repeats | muse-spark-open-1026 (Baseten) | 80 | ~1,204/call | ~1,817/call (~1,671 reasoning) | Baseten price not yet confirmed | – |
| 2026-10-27 | Verifier minimal-effort trial, dev, same 50 candidates | muse-spark-1.3 | 50 | 49,532 | 21,362 (15,022 reasoning) | 0.1190 | 0.8876 |
| 2026-10-27 | Agent dry run 1 (6-photo dev clip, uncached: SAM 6 images, verifier 28 candidates low, agent 11 turns) + replan | sam-3.1 + muse-spark-1.3 | 1 run | 127,608 | 29,236 | 0.1879 | 1.0755 |
| 2026-10-27 | Agent dry run 2 (cached perception/verification) + replan | muse-spark-1.3 | 1 run | – | – | 0.0468 | 1.1223 |
| 2026-10-27 | API smoke test via TestClient (cached run + one change) | muse-spark-1.3 | 1 run | – | – | 0.0360 | 1.1583 |
| 2026-10-27 | SAM test split, prompt "rust" (background, in progress; ~1,291 of 1,444 images at last check) | sam-3.1 | ~1,291 images | – | – | ~3.23 | ~4.39 |
| 2026-10-27 | Verifier at scale, test split, all 5,066 SAM candidates, reasoning low (incl. 310 verdicts from earlier interrupted chunks) | muse-spark-1.3 | 5,066 | – | mean 754 reasoning/call | 21.78 | ≈26.50 (ledger total $26.45 + ~$0.05 early probes) |
| 2026-10-27 | Recall experiment on dev: 2×2 tiling "rust" (200 tiles) + "rust stain" full frame (50) | sam-3.1 | 250 images | – | – | 0.625 | ≈27.13 |
| 2026-10-28 | Box-prompt recall experiment (dev 50 + test 1,444): Muse Spark minimal box proposals + SAM box prompts, incl. run before clamp fix | muse-spark-1.3 + sam-3.1 | 1,494 images | - | - | 8.28 (propose 4.55, SAM 3.73) | ~35.14 (ledger total $35.09 + ~$0.05 early probes) |
| 2026-10-28 | F1 senior review measurement: Muse Wonder on the 528 escalated test candidates (50-item dry run + rest) | muse-wonder-1.0 | 528 | - | mean 534 reasoning | 8.32 | - |
| 2026-10-28 | Baseten open verifier on test text-only candidates (stopped by the local memory guard at 1,169 of 1,444 images) | muse-spark-open-1026 (Baseten) | 3,784 | ~1,200/call | ~1,700/call (1,675 reasoning) | 31.79 (Baseten) | Meta unchanged |
| 2026-10-28 | Baseten resume: 55 images at max_tokens 8,000 (set aside for consistency, redone below) | muse-spark-open-1026 (Baseten) | 452 | - | - | 3.84 (Baseten) | - |
| 2026-10-28 | Baseten resume at max_tokens 4,000: remaining 275 images (2 processes) | muse-spark-open-1026 (Baseten) | 1,282 | - | - | 10.48 (Baseten) | - |
| 2026-10-28 | Baseten retry of the 92 invalid replies at max_tokens 8,000 (all recovered) | muse-spark-open-1026 (Baseten) | 92 | - | - | 1.05 (Baseten) | Baseten job total 47.15 |
| 2026-10-28 | Modal SAM 3.1 open weights: probe 1 crash-looped on a missing dependency (`psutil`; 13 container starts, 14:45-15:01 IST, stopped), CPU import check, probe 2 (upstream init_state kwargs mismatch), probe 3 OK (one frame, 10 instances) | Modal L40S + CPU | 4 runs | - | - | 0.095 (Modal billing report: crash loop 0.064, probe 3 0.012) | Modal ≈ 0.10 |
| 2026-10-28 | F2 On-prem end to end on devdemo: warm run (fill + repeat) and live Cloud vs On-prem comparison (Modal SAM 3.1 open weights, Baseten verifier + agent; Cloud run hosted) | sam-3.1 + muse-spark-1.3 + muse-wonder-1.0 / Modal L40S / muse-spark-open-1026 | 4 runs | - | - | Meta 0.20, Baseten 0.37, Modal ≈ 0.04 (ledger estimate at list rate) | - |
| 2026-10-28 | Open-weights mode: agent + verifier on Muse Spark Open, devdemo clip (fill run: 28 verifications + agent turns; repeat run: agent turns only) | muse-spark-open-1026 (Baseten) | 2 runs | - | - | 0.289 (Baseten, at the listed $1.25 / $0.15 / $4.25 per 1M) | Meta unchanged |
| 2026-10-28 | Box-candidate verification, test split: 5,385 new text+boxes candidates, reasoning low (first chunk 147 images, then 1,297 images with 3 processes) | muse-spark-1.3 | 5,385 | - | - | 23.02 | - |
| 2026-10-28 | Default-pipeline switch: box proposals + box SAM on the 6 devdemo frames (latency measurement, fills the cache), then demo cache refresh (fill + repeat agent runs incl. 4 senior reviews) | muse-spark-1.3 + sam-3.1 + muse-wonder-1.0 | 6 frames, 2 runs | - | - | 0.26 | ≈58.9 (ledger total $58.85 + ~$0.05 early probes) |
| 2026-10-28 | Adaptive packaging check on cached devdemo: one box candidate (F00005-b10) had no cached verdict after the F2 run (1 verify + senior check) | muse-spark-1.3 + muse-wonder-1.0 | 1 | - | - | < 0.02 (not ledgered: in-memory ledger) | - |
| 2026-10-28 | Teacher labels, clean train pool (585 images): SAM 3.1 open weights on Modal (dry run at new-detection threshold 0.65 on 15 images, set aside; then all 585 at 0.5) | Modal L40S | 600 images | - | - | 0.22 (ledger, list rate) | Modal ≈ 0.4 incl. box-exemplar probes and redeploys |
| 2026-10-28 | Teacher labels: Muse Spark Open verdicts on 1,298 open-weights candidates (dry runs 11 + 60 candidates included; 11 set aside with the 0.65 masks) | muse-spark-open-1026 (Baseten) | 1,309 | - | - | 10.95 (Baseten) | - |
| 2026-10-28 | Human audit evaluation: hosted minimal-effort verdicts for the 100 audited candidates | muse-spark-1.3 | 100 | - | - | 0.24 | - |
| 2026-10-28 | Synthetic negatives, evaluation only: Muse Image (dry run 10 + 290) | muse-image-1.0 | 300 images | - | - | 3.00 | - |
| 2026-10-28 | Box-only audit fill (hosted minimal + Muse Spark Open at 8,000 tokens on 50 candidates); On-prem box dev check (50 dev images: Muse Spark Open boxes + Modal SAM) | muse-spark-1.3 / muse-spark-open-1026 / Modal L40S | 50 + 50 | - | - | Meta ≈ 0.1, Baseten ≈ 1.0, Modal 0.05 | - |
| 2026-10-28 | False alarms on 191 public negatives, Cloud and On-prem (incl. 20-image dry runs) | sam-3.1 + muse-spark-1.3 / Modal + muse-spark-open-1026 | 191 x 2 | - | - | Meta 1.20, Baseten ≈ 1.25, Modal ≈ 0.04 | - |
| 2026-10-28 | Glimmer stage 1: weights to private Modal volume (59.6 GB, 263 s, CPU) | Modal CPU | 1 | - | - | ≈ 0.02 | - |
| 2026-10-28 | **Incident:** Glimmer smoke test stopped by the local low-memory guard during model load; the remote H100 kept running 21:06-21:09 IST until the ephemeral app was stopped (`modal app stop -y`), 0 containers confirmed. Since then every Modal GPU job runs with `modal run --detach` and a hard function timeout, results written to the volume, app/container lists checked after every job | Modal H100 | 1 | - | - | ≈ 0.2 | - |
| 2026-10-29 | Fireworks on-demand deployment (Glimmer baseline) refused: HTTP 400 "payment method is required". Builder decision: **skip on-demand deployments**; Fireworks used only for serverless inference (Muse Spark Open comparison, full-test-split On-prem benchmark). Glimmer evaluation moved to Modal | Fireworks | 0 | - | - | 0.00 | - |

## Credit pools: used vs target

Updated 2026-10-28, after the teacher-label run. Meta and Baseten figures come from the local ledgers (`G:/walkdown-data/runs/cost_ledger.jsonl` plus per-clip ledgers), priced at list prices. The builder checks the provider dashboards.

| Provider | Used | Target | Stop | Notes |
|---|---|---|---|---|
| Meta Model API | ≈ $67.8 | $120–135 | $140 | Box verification $23.02, F1 senior review $8.32, F2 comparison done |
| Baseten (Muse Spark Open) | ≈ $59.5 | ≈ $82 | $90 | Includes the Phase 4 dry run (80 calls, priced afterwards at $0.0085 per call) and the open-weights demo run |
| Fireworks | $0 | ≈ $80 | $90 | Dataset uploads still disabled; inference-only use (zero-shot Glimmer baseline) |
| Modal | ≈ $0.6 | ≈ $80 | $90 | SAM 3.1 open weights deployed (scale to zero, retries 0); no containers running after each job |

