# API cost log

Estimated from the `usage` fields returned by each call, using official prices:
- `muse-spark-1.3`: $1.25 / 1M input, $0.15 / 1M cached input, $4.25 / 1M output (reasoning tokens billed as output)
- `sam-3.1`: $2.50 / 1,000 images; video $0.20 / 1,000 frames, minimum 50 frames per request

Budget: target $50–70 Meta spend, hard stop $120.

| Date | Job | Model | Items | Input tokens | Output tokens | Est. $ | Running total $ |
|---|---|---|---|---|---|---|---|
| 2026-10-27 | Smoke test, run 1 (no reasoning effort set; reply empty, 200-token cap used up by reasoning) | muse-spark-1.3 | 1 | 17 | 200 | 0.000871 | 0.000871 |
| 2026-10-27 | Smoke test, run 2 (`reasoning.effort=minimal`) | muse-spark-1.3 | 1 | 17 | 75 (61 reasoning) | 0.000340 | 0.001211 |
