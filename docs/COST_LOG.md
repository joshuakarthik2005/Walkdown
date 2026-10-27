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
