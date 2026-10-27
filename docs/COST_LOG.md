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
| 2026-10-28 | Box-prompt recall experiment (dev 50 + test 1,444): Muse Spark minimal box proposals + SAM box prompts, incl. run before clamp fix | muse-spark-1.3 + sam-3.1 | 1,494 images | - | - | 8.28 (propose 4.55, SAM 3.73) | ~35.14 (ledger total .09 + ~.05 early probes) |
