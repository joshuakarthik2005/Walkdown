# Walkdown benchmark results

All numbers come from runs in this repository; the raw result files are in `benchmark/results/`. Dataset images are used **only for scoring**: none are shown here or anywhere public (see `docs/DECISIONS.md`). Planner results are in [`PLANNER_RESULTS.md`](PLANNER_RESULTS.md).

## 1. Perception: SAM 3.1 alone

**Setup**
- Model `sam-3.1` (Meta Model API), image mode, concept prompt **"rust"**.
- The prompt was chosen on the 50-image dev split before scoring the test split, and frozen. On dev, "rust" beat "corrosion" and "corroded metal" on recall and pixel IoU.
- Test split: **1,444 images, 9,812 annotated corrosion instances** (6.8 per image). These come from the Roboflow corrosion dataset's own valid and test folders after near-duplicate removal and exclusion of stock-photo-named images (`benchmark/splits/manifest.json`).
- Cost: 1,444 images × $0.0025 = **$3.61**. Result file: `results/sam_test_rust.json`.

![SAM 3.1 variants: pixel precision and recall](charts/perception_recall.svg)

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

## 3. Recall experiment: tiling and prompt unions (dev split only; negative result)

SAM 3.1 finds nothing in about a third of test images, and pixel recall is 0.36. Two standard fixes were tried **on the 50-image dev split only**, since test may not be used for tuning. Every variant goes through the same pipeline: masks are mapped to the full frame, then overlapping duplicates are merged (`backend/perception/tiling.py`). The baseline therefore differs slightly from §1's raw numbers.

| Variant (dev, 50 images, 320 GT instances) | Image detection | Pixel P / R / IoU | Instance P / R / F1 @ IoU 0.5 | Candidates / image | SAM cost / image |
|---|---|---|---|---|---|
| Full frame, "rust" (baseline) | 68.0% | 0.92 / 0.35 / 0.34 | 0.45 / 0.33 / 0.38 | 4.7 | $0.0025 |
| 2×2 tiles (15% overlap), "rust" | 70.0% | 0.87 / 0.32 / 0.30 | 0.28 / 0.33 / 0.30 | 7.6 | $0.0100 |
| Full frame, "rust" ∪ "corrosion" ∪ "rust stain" | 70.0% | 0.91 / 0.37 / 0.35 | 0.45 / 0.34 / 0.39 | 4.8 | $0.0075 |
| Full frame, "rust stain" alone | 50.0% | 0.91 / 0.23 / 0.22 | 0.50 / 0.26 / 0.34 | 3.3 | $0.0025 |

What happened:
- **Tiling does not help.** Pixel recall drops, and instance precision falls sharply (0.45 → 0.28) because regions get fragmented at tile scale. It costs 4× as much. Since 2×2 did not help, 3×3 was not tried.
- **The prompt union is marginal.** It gains +2 points of image detection (1 image of 50) and +0.017 pixel recall at 3× the cost. That is within what 50 images can resolve, not a clear improvement.

Decision: no variant clearly improves recall without hurting precision or tripling cost, so **nothing was frozen and nothing was run on the test split**. Walkdown keeps full-frame "rust". The ~1/3 of images with no detection stay a known limit of SAM 3.1 zero-shot on this dataset. Cost of the experiment: $0.625.

## 4. Box proposals + verification: text-only vs text + boxes vs text + boxes + verifier (test split)

**Setup**
- **Text only:** SAM 3.1, concept prompt "rust" (§1).
- **Text + boxes:** Muse Spark (`muse-spark-1.3`, reasoning effort **minimal**, strict JSON) looks at the full frame and lists up to 16 boxes around visible rust. SAM 3.1 segments each box (object prompts), and box masks are merged with the text masks (overlap merge, `backend/perception/tiling.py`). Designed on the dev split (`benchmark/box_prompt.py`), then run once on test.
- **+ verifier:** every merged candidate is verified by Muse Spark at low effort, exactly as in §2. A merged candidate that overlaps a text candidate at IoU ≥ 0.9 reuses that verdict; the **5,385 new candidates** were verified for this run (`benchmark/box_verify.py`). Rejected candidates are dropped before scoring.
- Same 1,444 images and 9,812 annotated instances as §1. Result files: `results/box_prompt_test.json`, `results/box_verify_test.json`.

| Pipeline (test, 1,444 images) | Image detection | Pixel P / R / IoU | Instance P / R / F1 @ IoU 0.5 | Instance P / R / F1 @ IoU 0.3 | Candidates / image | Cost / image |
|---|---|---|---|---|---|---|
| Text only | 65.6% | 0.92 / 0.36 / 0.35 | 0.51 / 0.26 / 0.34 | 0.56 / 0.29 / 0.38 | 3.5 | $0.0025 |
| Text only + verifier | 64.9% | 0.93 / 0.36 / 0.35 | 0.54 / 0.25 / 0.34 | 0.60 / 0.28 / 0.38 | 3.2 | $0.0176 |
| Text + boxes | **99.7%** | 0.75 / **0.87** / **0.67** | 0.38 / **0.32** / 0.35 | 0.46 / **0.38** / 0.42 | 5.6 | $0.0070 |
| **Text + boxes + verifier** | 97.9% | 0.77 / 0.84 / **0.67** | 0.47 / 0.30 / **0.37** | 0.56 / 0.36 / **0.44** | 4.3 | $0.038 |

Cost per image:
- SAM text call $0.0025.
- Box proposals: $0.0025 per image (Muse Spark, minimal effort).
- SAM box calls: $0.0020 per image on average (only images with boxes are sent).
- Verification: $0.0151 per image for text candidates, plus $0.0159 per image for the new box candidates.
  - That is $0.0043 per candidate.
  - Upper bound: verdicts of text candidates that were merged away are counted too.

**Does the verifier restore precision?** Mostly, at the instance level. Box proposals cost 12 points of instance precision at IoU 0.5 (0.51 to 0.38); the verifier wins back 9 of them (0.47). At IoU 0.3 it wins back nearly all of the 10-point loss (0.46 to 0.56; text only 0.56). Pixel precision recovers only slightly (0.75 to 0.77; text only 0.92): the box masks are larger and less tight than text masks, and the verifier accepts or rejects a candidate, it does not tighten its mask.
- Recall cost of verification: image detection 99.7% to 97.9%, instance recall 0.32 to 0.30. Among the new box candidates mostly inside annotated corrosion (coverage ≥ 0.5, n = 2,859), the verifier keeps **89.9%**; over all merged candidates 91.8%. That is lower than for text candidates (95.5%, §2): box candidates are more often borderline.
- Invalid replies on the 5,385 new candidates: **0**. Median latency per verification call 6.0 s. The verifier accepted 72.6% of new candidates (89.8% of text candidates).
- **Text + boxes + verifier has the best instance F1 at both thresholds and the best pixel IoU, and finds corrosion on 98% of positive images instead of 66%.** It is the default pipeline (see `docs/DECISIONS.md`).
- The same caveat as §2 applies: precision here is measured against dataset labels that leave real rust unannotated, so measured precision is a lower bound and FP rejection is not measured. False alarms on clean surfaces are still unmeasured (no negative images in the dataset; pending the builder's negative footage).

Cost of this experiment: box proposals and box masks $6.50, verification of new candidates $23.02.

## 5. Senior review (F1): Muse Wonder on escalated grades (test split)

**Setup**
- Every text-only test candidate (§2) whose first-pass grade (hosted Muse Spark, low effort) either accepts a defect at severity ≥ 4 or has confidence below 0.6 goes to **`muse-wonder-1.0`**. Muse Wonder gets the same prompt, images and strict schema, at low effort.
- Result file: `results/senior_eval_test_low.json` (50-item dry run: `results/senior_eval_test_low_n50.json`). Script: `benchmark/senior_eval.py`.

| Metric | Value |
|---|---|
| Escalated | **528 of 5,066** (10.4%): 324 for severity ≥ 4, 204 for confidence < 0.6 |
| Invalid senior replies | 0 |
| Decision changed | 54 (10.2%), **all accept → reject**; none reject → accept |
| Severity changed (both accepted, n = 473) | 179 (38%); mean change −0.14 (slightly milder) |
| Agreement with coverage labels (TP/FP, n = 517) | first pass 73.5%, after senior review 72.7% |
| Annotated-corrosion candidates kept (TP, n = 379) | first pass 100%, senior 92.3% (29 rejected) |
| "FP" candidates rejected (n = 138; labels NOT reliable, §2) | first pass 0.7%, senior 18.8% (26) |
| Cost | $8.32 total, **$0.0158 per review**; ≈ $0.0016 per verified candidate on average (+38% over first pass) |
| Latency | median 7.8 s, p90 10.8 s per review (added only for escalated candidates) |

What this shows:
- Muse Wonder is a **more conservative second opinion**. It rejects about one in ten escalated accepts and grades severity a little lower.
- Against the dataset labels it is **not more accurate** (72.7% vs 73.5%). It rejected 29 annotated-corrosion candidates and 26 candidates labelled FP, and the FP labels are known to miss real rust.
- **Product rule changed because of this measurement (fail-safe).**
  - A defect the first pass accepted and Muse Wonder rejects is no longer dropped.
  - It stays in the register with the first-pass grade, flagged `senior_disputed`, and goes to human review.
  - For severity changes, Muse Wonder's grade stays final; the first-pass severity is shown next to it.
- With this rule, senior review loses no recall. What it adds is a disagreement signal on about 1% of candidates (54 of 5,066), sent to a human. It also gives a second severity opinion on the severe ones.

## 6. Open weights: Muse Spark Open (Baseten) vs hosted Muse Spark on all 5,066 candidates (test split)

**Setup**
- The same 5,066 text-only test candidates, prompt and images as §2, verified by **`meta-models/muse-spark-open-1026`** on Baseten.
- Baseten does not offer structured outputs, so the JSON schema is in the prompt, and each reply is parsed and validated (one automatic re-ask on a malformed reply).
- **Same conditions as the hosted run:** every candidate was verified with **max_tokens = 4,000**.
  - The run was resumed after the local memory guard stopped it.
  - 55 images had briefly run at 8,000 tokens. Their verdicts were set aside and redone at 4,000 so all candidates share one setting.
- **Retry setting.** Only the candidates whose reply was still invalid at 4,000 tokens were re-verified at **max_tokens = 8,000** (`benchmark/verify_retry.py`). The product's On-prem verifier now uses 8,000 by default.
- Files:
  - `results/verify_scale_test_baseten_low.json` (the 4,000-token run)
  - `results/verify_retry_test_baseten_low.json` (the retry)
  - the hosted run is §2.

| Metric (5,066 candidates) | Muse Spark Open, 4,000 tokens | **+ retry of invalid replies at 8,000** | Hosted Muse Spark (§2) |
|---|---|---|---|
| Invalid replies | 92 (1.82%) | **0 (0.00%)**: all 92 recovered | 0 (strict schema) |
| Same accept/reject decision as hosted | 93.3% | **93.4%** | – |
| Severity when both accept: exact / within ±1 | 68.2% / 99.2% (n = 4,367) | **68.1% / 99.1%** (n = 4,418) | – |
| TP retention (coverage ≥ 0.5, n = 3,616) | 96.7%* | **96.4%** | 95.5% |
| Accepted share | 91.8%* | 91.3% | 89.8% |
| Reasoning tokens per call (mean) | 1,668 | – | 754 |
| Cost per candidate | $0.0083 | retry: $0.0115 per retried candidate | $0.0043 |
| Latency per call: median / p90 | 10.9 s / 15.8 s | retry median 13.9 s | 5.3 s / 25.6 s |
| Total cost | $42.27 | + $1.05 | $21.78 |

\* Invalid replies count as accepted (fail open: they go to human review). That is why the 4,000-token column is slightly higher.

- **Open weights are a usable on-prem verifier.**
  - It agrees with hosted Muse Spark on 93.4% of decisions, and severities are within one grade 99.1% of the time.
  - It keeps slightly more annotated corrosion (96.4% vs 95.5%).
- **The 1.8% invalid replies were an output budget problem, not a model failure.** Muse Spark Open reasons for about twice as many tokens, and without strict decoding a long reasoning trace can use up 4,000 tokens before the JSON. At 8,000 tokens every one of them returned a valid grade. Of the 92: 65 accepted, 27 rejected; labels 47 TP, 41 FP, 4 ambiguous.
- **The cost of open weights here** is about 2× tokens per candidate and about 2× median latency. (Its p90 latency is lower than the hosted run's, which had a slow phase; see §2's throughput note.)
- Job cost: $47.15 of Baseten credit in total. That is the 4,000-token run ($42.27), the set-aside 8,000-token verdicts ($3.84) and the retry ($1.05).
