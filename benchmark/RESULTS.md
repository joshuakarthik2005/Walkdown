# Walkdown benchmark results

All numbers come from runs in this repository; the raw result files are in `benchmark/results/`. Dataset images are used **only for scoring**: none are shown here or anywhere public (see `docs/DECISIONS.md`). Planner results are in [`PLANNER_RESULTS.md`](PLANNER_RESULTS.md).

## 1. Perception: SAM 3.1 alone

**Setup**
- Model `sam-3.1` (Meta Model API), image mode, concept prompt **"rust"**.
- The prompt was chosen on the 50-image dev split before scoring the test split, and frozen. On dev, "rust" beat "corrosion" and "corroded metal" on recall and pixel IoU.
- Test split: **1,444 images, 9,812 annotated corrosion instances** (6.8 per image). These come from the Roboflow corrosion dataset's own valid and test folders after near-duplicate removal and exclusion of stock-photo-named images (`benchmark/splits/manifest.json`).
- Cost: 1,444 images × $0.0025 = **$3.61**. Result file: `results/sam_test_rust.json`.

| Level | Metric | Value |
|---|---|---|
| Instance, IoU ≥ 0.5 | precision / recall / F1 | **0.51 / 0.26 / 0.34** (TP 2,560, FP 2,506, FN 7,252) |
| Instance, IoU ≥ 0.3 | precision / recall / F1 | 0.56 / 0.29 / 0.38 |
| Instance | mean IoU of matched pairs | 0.82 (IoU ≥ 0.5), 0.78 (IoU ≥ 0.3) |
| Pixel (union of masks per image) | precision / recall / IoU | **0.92 / 0.36 / 0.35**; mean per-image IoU 0.46 |
| Image ("any corrosion found") | detection rate on positive images | **65.6%** (947 of 1,444) |
| Image | false-alarm rate on negative images | not measurable yet: the dataset has **no negative images** |
| Output size | SAM instances per image | 3.5 (ground truth: 6.8) |

### Reading these numbers: the granularity mismatch

- Instance-level scores understate SAM, because the dataset and SAM split corrosion differently.
- The annotators traced rust as **many small patches**: 6.8 per image on average, a quarter of them under 500 px. SAM returns **fewer, larger regions**, often one region covering several annotated patches.
- One-to-one matching at IoU ≥ 0.5 counts such a region as at most one TP, or as an FP if it is much larger than any single patch, and counts the remaining patches as FNs.
- The pixel level shows the other side. **92% of the pixels SAM marks as rust are annotated rust**, and when SAM does match an instance, the masks agree closely (IoU 0.82).

Where SAM is genuinely weak:
- **Recall.** It covers 36% of annotated rust pixels, and finds nothing at all in 34% of images.
- **No low-confidence output.** SAM returns nothing below confidence ~0.5, so recall can't be raised by lowering a threshold.

For Walkdown this sets the design: SAM proposes, Muse Spark verifies. SAM's misses can't be recovered downstream, which is why the prompt was chosen for recall.

### What is not measured yet
- **False alarms on clean surfaces.** Every test image contains corrosion. The builder is recording negative footage (clean and look-alike surfaces); see `benchmark/build_negatives.py`. Image-level false-alarm rate and candidate counts on negatives will be added when it exists.
- **Video mode.** SAM 3.1 video requests are accepted and billed, but returned no detections on a synthetic clip. The demo uses frame-by-frame image calls until video is re-tested on real footage.

## 2. Verification: Muse Spark on every SAM candidate

**Setup**
- Every SAM 3.1 "rust" candidate on the test split (**5,066 candidates** on 1,444 images) is verified by hosted **`muse-spark-1.3`**, reasoning effort **low**.
- Each call gets a 448 px crop with the mask outlined in cyan plus a 256 px frame thumbnail. The reply is strict JSON-schema output: is_defect, defect_type, severity 1–5, confidence, evidence, recommended_action.
- Result file: `results/verify_scale_test_meta_low.json`. The verdict cache and per-image journal are on `WALKDOWN_DATA_DIR`.

| Metric | Value |
|---|---|
| Candidates verified | 5,066 (complete) |
| Invalid replies (schema or JSON failures) | **0** (0.0%) |
| Accepted as defect | 4,549 (89.8%); rejected 517 |
| **TP retention**: share of candidates mostly inside annotated corrosion (coverage ≥ 0.5, n = 3,616) that the verifier keeps | **95.5%** |
| Consistency flags raised | 2 (both "poor mask fit") |
| Severity of accepted candidates (1 / 2 / 3 / 4 / 5) | 170 / 2,521 / 1,534 / 290 / 34 |
| Cost | **$21.78** total, **$0.0043 per candidate** (754 reasoning tokens on average; the fixed prompt prefix is cached) |
| Latency per call | median 5.3 s, p90 25.9 s |
| Throughput | 8 concurrent calls (4 processes × 2): 74 calls/min in the final clean chunk; much lower earlier in the run (see below) |

**Severity is not accuracy.** There is no severity ground truth, so no accuracy is claimed. What was measured is consistency: on 30 dev candidates graded twice, is_defect agreed 100%, severity matched exactly 97% of the time and within ±1 100% of the time. Hosted and open-weights Muse Spark agreed on is_defect for 96% of 50 dev candidates.

### Why dataset labels do not measure false-positive rejection
- A candidate is labelled "FP" when less than 10% of its pixels lie inside annotated corrosion (n = 1,325). Against that label the verifier "rejects" only 25.1%, and candidate precision moves from 0.73 (SAM alone) to 0.78 (SAM + verifier).
- **These two numbers are not a valid FP-rejection metric.** A private visual check of labelled-FP crops showed that many are real rust or rust staining the annotators did not mark: the dataset annotates *some* rust patches per image, not all of them.
- A verifier that correctly accepts unannotated rust is therefore scored as failing to reject false positives.
- The dataset also contains **no negative images**, so the verifier was never shown clean or look-alike surfaces in this benchmark.
- What can be said honestly: the verifier keeps 95.5% of annotated corrosion (its cost in missed defects is small), its outputs are always well-formed, and it is consistent.
- How often it rejects real false positives will be measured on:
  1. the builder's negative footage: clean and look-alike surfaces, all of which should be rejected
  2. the ~100 audited labels from the local labelling page (`benchmark/label_app.py`), reported side by side with the coverage labels.

### Throughput note
- At the start of this run, throughput sat at about 16 calls/min and latency rose to a 48 s median with 32 calls in flight. I first recorded that as a server-side cap.
- That was wrong, or at most temporary. The same configuration later sustained 74 calls/min, and part of the early slowness came from this benchmark's own worker crashes and pure-Python mask decoding.
- Throughput from the Meta API varied by a factor of ~4 over a few hours, with no 429s. The live demo uses cached perception and verification so it does not depend on it.
