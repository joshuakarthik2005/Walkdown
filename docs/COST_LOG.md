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
| 2026-10-28 | Open-weights mode: agent + verifier on Muse Spark Open, devdemo clip (fill run: 28 verifications + agent turns; repeat run: agent turns only) | muse-spark-open-1026 (Baseten) | 2 runs | - | - | 0.289 (Baseten, at the listed $1.25 / $0.15 / $4.25 per 1M) | Meta unchanged |
| 2026-10-28 | Box-candidate verification, test split: 5,385 new text+boxes candidates, reasoning low (first chunk 147 images, then 1,297 images with 3 processes) | muse-spark-1.3 | 5,385 | - | - | 23.02 | - |
| 2026-10-28 | Default-pipeline switch: box proposals + box SAM on the 6 devdemo frames (latency measurement, fills the cache), then demo cache refresh (fill + repeat agent runs incl. 4 senior reviews) | muse-spark-1.3 + sam-3.1 + muse-wonder-1.0 | 6 frames, 2 runs | - | - | 0.26 | ≈58.9 (ledger total $58.85 + ~$0.05 early probes) |

## Credit pools: used vs target

Updated 2026-10-28, after the box-candidate verification run. Meta and Baseten figures come from the local ledgers (`G:/walkdown-data/runs/cost_ledger.jsonl` plus per-clip ledgers), priced at list prices. The builder checks the provider dashboards.

| Provider | Used | Target | Stop | Notes |
|---|---|---|---|---|
| Meta Model API | ≈ $67.2 | $120–135 | $140 | Box verification $23.02, F1 senior review $8.32 done |
| Baseten (Muse Spark Open) | ≈ $32.8 | ≈ $82 | $90 | Includes the Phase 4 dry run (80 calls, priced afterwards at $0.0085 per call) and the open-weights demo run |
| Fireworks | $0 | ≈ $80 | $90 | Dataset uploads still disabled; inference-only use (zero-shot Glimmer baseline) |
| Modal | ≈ $0 (CPU image build only) | ≈ $80 | $90 | Payment method added (workspace limit $100); GPU jobs queued |

