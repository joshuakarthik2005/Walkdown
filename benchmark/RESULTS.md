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
