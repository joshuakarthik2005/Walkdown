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

## 7. Cloud vs On-prem mode, end to end (F2)

**Setup**
- One live agent run per mode on the 6-photo dev clip (`devdemo`, dataset images, scoring only). Every model call is live: no perception or verdict cache. Verifier at minimal effort, as in the demo. Script: `benchmark/mode_compare.py`; result file: `results/mode_compare_devdemo.json`.
- **Cloud:**
  - hosted SAM 3.1: text prompt plus Muse Spark box proposals
  - Muse Spark as verifier and agent
  - Muse Wonder senior review
- **On-prem:** open weights only.
  - SAM 3.1 open weights on Modal: one L40S that scales to zero (`modal_apps/sam_open.py`), text prompt only
  - Muse Spark Open on Baseten as verifier and agent
  - no hosted model is called

| devdemo, 6 photos | Cloud | On-prem |
|---|---|---|
| SAM candidates | 50 (text + boxes) | 17 (text only) |
| Accepted by the verifier / register entries | 29 / 29 | 17 / 17 |
| Walkdown jobs (work packages) | 5 | 5 |
| Plan | OPTIMAL, gap 0 | OPTIMAL, gap 0 |
| Entries needing review | 1 | 0 |
| Agent turns | 8 | 7 |
| Wall time, whole run | 98 s | 73 s (includes Modal cold start) |
| of which segmentation | 52.7 s (text SAM + box proposals + box SAM) | 30.4 s (cold start + 6 frames) |
| of which verification | 28.8 s | 27.0 s |
| Cost | $0.201 | $0.175 (Modal GPU ≈ $0.016 at the L40S list rate, Baseten $0.158) |

What it shows:
- On-prem runs the whole loop on open weights and produces a plan to the same standard: perceive, verify, register, plan (OPTIMAL) and explain.
- It finds fewer candidates because it has **no box proposals**. Box proposals use hosted Muse Spark with strict JSON, which the open stack does not have yet.
- Segmentation recall should therefore be expected to match the text-only column of §4 (66% image detection on test), not the default pipeline's 98%.
- SAM 3.1 open weights and hosted SAM 3.1 were not compared mask-for-mask on the test split. On this clip the open weights returned 17 instances against 28 from the hosted text prompt, at the predictor's default 0.5 output threshold.
- This is one 6-image clip, so it is a functional check of the mode, not a benchmark.
- Every Modal container scaled to zero after the run.

## 8. Human-audited evaluation (n = 100)

- **Sample.** 100 SAM 3.1 text-prompt candidates from the test split, stratified by the dataset coverage label (40 "TP", 40 "FP", 20 "ambiguous"; `benchmark/label_app.py`, seeded). The builder labelled each crop rust / not rust / unsure without seeing the dataset label or any verdict.
- **Labels:** 82 rust, 7 not rust, **11 unsure** (9 of them dataset "FP", 2 dataset "TP"). Unsure is excluded from every metric below.
- **Two views of every metric.** "Sample" counts the 89 sure labels as drawn. "Reweighted" corrects the stratified draw to the test split's candidate mix (3,616 TP / 1,325 FP / 125 ambiguous). 95% intervals: Wilson for the sample, stratified bootstrap for reweighted.
- Script: `benchmark/audit_eval.py`; result: `results/audit_eval.json`. Cost: $0.24 (hosted minimal-effort verdicts for the 100 candidates; all other verdicts were cached).

### Dataset labels vs the human (the annotation gap)

| Dataset coverage label | Human: rust | not rust | unsure |
|---|---|---|---|
| "TP" (40) | 37 | 1 | 2 |
| "FP" (40) | **26** | 5 | 9 |
| "ambiguous" (20) | 19 | 1 | 0 |

- **84% of dataset "false positives" are rust to a human** (26 of 31 sure labels; 95% CI 67–93%). The dataset's polygons miss much of the visible rust, so the "FP" label mostly marks unannotated rust, not false alarms.
- The dataset "TP" label is reliable: 1 of 38 was not rust (CI 0.5–13.5%).
- On TP/FP candidates, dataset label and human agree only **61%** of the time (42 of 69; CI 49–72%).
- This confirms, with human labels, the finding in §2: FP rejection measured against dataset labels is not a valid metric, and pixel/instance precision against the masks understates real precision.

### How many SAM text-prompt candidates are real rust

- **92% of text-prompt candidates are rust** (82 of 89; CI 85–96%); reweighted to the test mix, **94%**.
- So the text prompt "rust" mostly finds real rust. Its weakness is recall (§1), not precision.
- **Text+boxes candidates were not audited.** The sample predates box proposals, so it contains text-prompt candidates only. The share of box-only candidates that is real rust is **not measured**. Box-only candidates are where §4 found the extra false alarms, so this is the open question. A 50-candidate audit of box-only candidates is proposed.

### Verifiers vs the human (89 sure labels; invalid replies count as accept)

| Verifier | TP | FP | FN | TN | Precision (sample, 95% CI) | Recall (sample, 95% CI) | Accuracy (sample, 95% CI) | Not-rust rejected | Reweighted P / R / accuracy |
|---|---|---|---|---|---|---|---|---|---|
| Hosted Muse Spark, low | 72 | 2 | 10 | 5 | 97.3% (90.7–99.3) | 87.8% (79.0–93.2) | 86.5% (77.9–92.1) | 5 of 7 | 97.7% / 90.0% / 88.6% |
| Hosted Muse Spark, minimal (live demo setting) | 79 | 3 | 3 | 4 | 96.3% (89.8–98.7) | **96.3%** (89.8–98.7) | **93.3%** (86.1–96.9) | 4 of 7 | 97.0% / 97.0% / 94.3% |
| Muse Spark Open (Baseten), low | 77 | 2 | 5 | 5 | 97.5% (91.2–99.3) | 93.9% (86.5–97.4) | 92.1% (84.6–96.1) | 5 of 7 | 97.8% / 94.4% / 92.7% |
| Product with senior review (low + Muse Wonder, fail-safe) | 72 | 2 | 10 | 5 | 97.3% | 87.8% | 86.5% | 5 of 7 | same as low |

- Raw intervals for every row and the reweighted bootstrap intervals are in the JSON.
- **The verifier is mostly a recall cost on this sample.** 92% of the candidates are rust, so accepting everything would already score 92% precision.
- The verifier rejected 4 or 5 of the 7 not-rust candidates, but **n = 7 is far too small to estimate false-positive rejection** (Wilson intervals 36–92% for low effort and Muse Spark Open, 25–84% for minimal).
- What the audit does show is how much real rust each verifier wrongly rejects:
  - hosted low effort rejected 12% (10 of 82);
  - Muse Spark Open rejected 6%;
  - minimal effort rejected 4%.
- The differences between the verifiers are within the confidence intervals: low vs minimal recall intervals overlap. Treat them as indicative.
- **Senior review.** 13 of the 89 were escalated; Muse Wonder agreed with the first pass on all 13, so on this sample it **overturned nothing**. Whether its overturned verdicts match a human therefore **cannot be assessed from this audit**. The §5 statement stands: it is a second opinion that surfaces disputes, with no measured accuracy gain.
- **Not measured here:** false-positive rejection (needs many more not-rust candidates: the builder's negatives footage and public negatives sets), box-only candidates, severity accuracy.

### On-prem box proposals: dev check (50 dev images)

- **Pipeline.** Same as Cloud's second perception path, open weights only. Muse Spark Open (Baseten) proposes rust boxes on the full frame, using the Cloud prompt with JSON parsed from text. SAM 3.1 open weights then segment them on Modal.
- **Why exemplars.** The open-weights multiplex model has no per-object box prompt, so the boxes go in as visual exemplars and each box keeps its best-overlapping detection (box IoU ≥ 0.3).
- **Threshold change.** The open-weights single-image detection threshold is now 0.5, the floor the hosted SAM returns; the video default is 0.65.
- Script: `benchmark/open_boxes.py`; result: `results/open_boxes_dev.json`. Candidates are unverified, scored against the dataset masks.

| dev, 50 images | Image detection | Pixel recall | Pixel precision | Instance P / R / F1 @0.5 | Candidates / image |
|---|---|---|---|---|---|
| On-prem text only (open weights) | 68% | 33.6% | 92.4% | 0.51 / 0.33 / 0.40 | 4.1 |
| On-prem boxes only | 90% | 49.6% | 68.7% | 0.21 / 0.09 / 0.13 | 2.9 |
| **On-prem text + boxes** | **100%** | **65.0%** | 72.8% | 0.37 / 0.33 / 0.35 | 5.6 |
| Cloud text only (hosted) | 68% | 35.1% | 92.1% | 0.45 / 0.33 / 0.38 | 4.7 |
| Cloud text + boxes (hosted) | 100% | 90.3% | 82.0% | 0.44 / 0.40 / 0.42 | 5.8 |

- **Box proposals close the image-detection gap.** On-prem now finds corrosion on every annotated dev image, as Cloud does.
- **Area covered roughly doubles,** from 34% to 65% of the annotated pixels. That is still well below Cloud's 90%.
  - 146 of the 183 proposed boxes got an open-weights mask; the rest had no overlapping detection.
  - Exemplar masks match the box less tightly than hosted per-box prompts.
- Box proposals also lower pixel precision, as in Cloud (§4 and the box audit below), so the verifier matters more.
- **Cost:** box proposals $0.012 per image (Muse Spark Open; median latency 20.9 s per call, in parallel across frames); Modal $0.001 per image.
- **Decision (builder, 2026-10-28): On-prem mode is now text + boxes + verifier.**
- **Test split: not run yet.** The full 1,444 images with verification would cost ≈ $35 on Baseten (≈ $17 proposals + ≈ $18 verifying the new candidates), which would cross the $90 Baseten stop. Options are in the checkpoint report.

### Box-only candidates (second audit, n = 50)

- **Sample.** 50 box-only candidates from the test split: merged text + boxes candidates that are new, not a reused text-prompt candidate. Stratified by dataset label: 20 "TP", 20 "FP", 10 "ambiguous" (`benchmark.label_app --set boxes`, seeded, same blind protocol).
- **Labels:** 31 rust, 13 not rust, 6 unsure. Reweighting uses the 5,385 new box candidates (2,859 TP / 1,852 FP / 674 ambiguous).
- Script: `benchmark/audit_boxes_eval.py`; result: `results/audit_boxes_eval.json`. Cost: $0.52 (hosted minimal and Muse Spark Open verdicts for the 50; Muse Spark Open at the product setting, max_tokens 8,000).

| Dataset label | Human: rust | not rust | unsure |
|---|---|---|---|
| "TP" (20) | 14 | 4 | 2 |
| "FP" (20) | 9 | 8 | 3 |
| "ambiguous" (10) | 8 | 1 | 1 |

**Do box proposals add false alarms? Yes.**

| Candidates | Real rust (human) | 95% CI |
|---|---|---|
| Text-prompt (first audit) | 92.1% (82 of 89) | 84.6–96.1% |
| Box-only (this audit) | **70.5%** (31 of 44); reweighted 70.6% | 55.8–81.8% |
| Difference (box − text) | −21.7 points | −36.9 to −8.1 (Newcombe) |

- **About 3 in 10 box-only candidates are not rust**, against 1 in 13 for text-prompt candidates.
- Box proposals buy recall (§4), and the verifier must remove the extra look-alikes.
- Dataset "FP" box candidates are about half rust (9 of 17), so the annotation gap shows up here too.

**Verifiers on box-only candidates (44 sure labels):**

| Verifier | TP | FP | FN | TN | Precision (sample, 95% CI) | Recall (sample, 95% CI) | Not-rust rejected | Reweighted P / R |
|---|---|---|---|---|---|---|---|---|
| Hosted Muse Spark, low | 30 | 4 | 1 | 9 | 88.2% (73.4–95.3) | 96.8% (83.8–99.4) | **9 of 13** | 87.3% / 97.1% |
| Hosted Muse Spark, minimal | 31 | 5 | 0 | 8 | 86.1% (71.3–93.9) | 100% (89.0–100) | 8 of 13 | 85.5% / 100% |
| Muse Spark Open (Baseten) | 31 | 5 | 0 | 8 | 86.1% (71.3–93.9) | 100% (89.0–100) | 8 of 13 | 86.2% / 100% |

- On box candidates the verifier does real work: it raises precision from 70% to 86–88% and rejects 8 or 9 of the 13 not-rust candidates.
- It still lets about a third of box look-alikes through.

### Combined audit (text-prompt + box-only, n = 133 sure labels)

Reweighted over six strata (source × dataset label) to the default pipeline's candidate mix. This is approximated as all 5,066 text-prompt candidates plus all 5,385 new box candidates.

- **Real rust among all candidates:** 85.0% in the sample (113 of 133; 95% CI 77.9–90.0%); **81.8% reweighted**.
- **Not-rust candidates rejected** (20 not-rust in total):
  - low: 14 of 20 (95% CI 48–86%);
  - Muse Spark Open: 13 of 20 (43–82%);
  - minimal: 12 of 20 (39–78%).

| Verifier (combined, reweighted) | Precision (95% bootstrap CI) | Recall (95% CI) | Accuracy (95% CI) |
|---|---|---|---|
| Hosted Muse Spark, low | 92.6% (85.9–97.9) | 93.2% (88.1–97.2) | 88.3% (81.8–93.9) |
| Hosted Muse Spark, minimal | 91.4% (85.1–97.0) | **98.3%** (95.6–100) | **91.1%** (85.0–96.4) |
| Muse Spark Open (Baseten) | 92.1% (85.6–97.5) | 96.9% (93.4–99.1) | 90.6% (84.4–95.7) |

- **What this means for the default pipeline.** About 8% of what the register shows is not rust.
- The verifier rejects about two thirds of the look-alikes, and drops 2–7% of real rust, depending on the verifier.
- The three verifiers' intervals overlap. Low effort trades a few more rejected look-alikes for more missed rust.
- Still not measured: false alarms on clean surfaces with no rust at all (the negatives sets).

## 9. False alarms on public negatives (191 non-corroded pipe images)

- **Set.** 191 unique images of non-corroded pipes: painted, coated, stainless and galvanised (`docs/FOOTAGE_SOURCES.md`).
  - Sources: Roboflow `corrosion-detection-sd` "Non-Corroded" classes, CC BY 4.0. Deduplicated by source name and dHash.
  - Use: scoring only, never public, never trained on.
  - Reported separately from the builder's own footage, which is still pending.
- **Label caveat.** "Non-corroded" is the dataset's label, not a human audit. A contact sheet of the Cloud-accepted images shows mostly clean pipes, but a few have minor brown staining at supports or joint bands. Treat these rates as upper bounds on true false alarms.
- **Metric.** Share of images with at least one candidate, or with at least one candidate the verifier accepts (what the register would show). Wilson 95% CIs.
- **Pipelines:**
  - Cloud: hosted SAM 3.1 plus Muse Spark boxes; verifier is Muse Spark at minimal effort (the live-demo setting).
  - On-prem: SAM 3.1 open weights plus Muse Spark Open boxes; verifier is Muse Spark Open.
- Script: `benchmark/negatives_fp.py`; results: `results/negatives_fp_public_{cloud,on-prem}.json`. Cost: Meta $1.20, Baseten ≈ $1.25, Modal ≈ $0.04.

| Images with a false alarm (of 191) | Text only | Text + boxes | Text + boxes + verifier |
|---|---|---|---|
| Cloud | 4.2% (8; CI 2.1–8.0) | 31.9% (61; CI 25.7–38.8) | **12.0%** (23; CI 8.2–17.4) |
| On-prem | 3.1% (6; CI 1.4–6.7) | 19.4% (37; CI 14.4–25.6) | **2.1%** (4; CI 0.8–5.3) |

| Candidates per image | Text only | Text + boxes | Accepted |
|---|---|---|---|
| Cloud | 0.11 | 0.97 | 0.21 |
| On-prem | 0.08 | 0.55 | 0.04 |

**Same Cloud candidates, every verifier** (item 2 of the overnight run, `--all-verifiers`; 185 text + boxes candidates on the 191 images):

| Verifier on the Cloud text + boxes candidates | Images with a false alarm (95% CI) | Accepted candidates per image |
|---|---|---|
| None (text + boxes) | 31.9% (25.7–38.8) | 0.97 |
| Hosted Muse Spark, minimal (demo setting) | 12.0% (8.2–17.4) | 0.21 |
| Hosted Muse Spark, low | 6.8% (4.0–11.3) | 0.12 |
| Muse Spark Open (Baseten) | **4.2%** (2.1–8.0) | 0.06 |

- On real clean pipes, minimal effort is the weakest verifier. Low effort halves its false alarms, and Muse Spark Open cuts them by about two thirds.
- This matches the audit, where minimal also accepted the most look-alikes, at the price of rejecting less real rust (§8).

What it shows:
- **The text prompt alone rarely fires on clean pipes:** 3–4% of images.
- **Box proposals are the main source of false alarms** on clean surfaces: 19–32% of images. This agrees with the box audit in §8.
- **The verifier removes most of them, but not equally.**
  - Cloud at minimal effort still accepts a look-alike on 12% of clean images (23 images, 41 candidates). Muse Spark Open accepts one on 2%.
  - The Cloud verifier sees more box candidates: hosted per-box prompts produce more masks than the open-weights exemplar matching.
  - The two verifiers judge different candidate sets, so this is a pipeline comparison, not a head-to-head of the verifiers.
- **Implication for the demo.** On clean plant footage, Cloud mode at minimal effort can put a false defect in the register on roughly 1 frame in 8. The builder's own negatives footage will measure this on realistic frames. Low-effort verification or a stricter box filter would be the levers.

## 10. Synthetic look-alike stress test (Muse Image, evaluation only)

- **Set.** 300 images from `muse-image-1.0`: plant pipes, tanks, valves and flanges with rust look-alikes and **no corrosion** by prompt.
  - 15 look-alike categories (paint, tape, shadows, wet patches, stains, dirt, wood, copper tubing, …) × 5 plant settings; each image's prompt is in `G:/walkdown-data/synthetic/muse_eval/manifest.jsonl`.
  - Hosted Meta outputs, so **evaluation only** (Meta Model API terms 10.1(ix)). Never trained on, never published. Cost $3.00.
- **Labels are by prompt, not human-checked.** Four categories render marks a person may call rust staining: brown oil smudges, brown paint drips, dark water stains, and safety-yellow paint with brown dirt smears. Rates are given with and without them.
- Script: `benchmark/negatives_fp.py synthetic_muse` (Cloud with `--all-verifiers`: the same Cloud candidates judged by every hosted verifier and by Muse Spark Open). Results: `results/negatives_fp_synthetic_muse_{cloud,on-prem}.json`. Cost: Meta ≈ $1.7, Baseten ≈ $4.0 (On-prem box proposals and verification).

**Images with a false alarm (95% Wilson CI)**

| Pipeline stage | Cloud, all 300 | Cloud, 221 without the 4 ambiguous categories | On-prem, all 300 | On-prem, 221 |
|---|---|---|---|---|
| Text prompt only | 15.3% (11.7–19.8) | 5.0% (2.8–8.7) | 13.7% (10.2–18.0) | 4.1% (2.2–7.6) |
| Text + boxes | 40.0% (34.6–45.6) | 23.1% (18.0–29.1) | 21.0% (16.8–26.0) | 6.3% (3.8–10.4) |
| + hosted Muse Spark, minimal (demo) | 25.7% (21.1–30.9) | 9.0% (5.9–13.6) | – | – |
| + hosted Muse Spark, low | 21.7% (17.4–26.7) | 5.9% (3.5–9.8) | – | – |
| + Muse Spark Open | 26.7% (22.0–31.9) | 8.1% (5.2–12.5) | 15.0% (11.4–19.5) | 2.3% (1.0–5.2) |

- **Box proposals are again the main source of false alarms.** Cloud's hosted per-box prompts produce more candidates than On-prem's exemplar matching (1.6 vs 1.1 per image).
- **The verifiers remove about half of the box look-alikes.** Low effort is the strictest.
- **Clear look-alikes are easy.** Paint, tape, arrows, shadows, reflections and wet patches: 0–5% after any verifier.
- **Brown stains, smudges and drips are not.** Oil smudges were accepted on 89–100% of images and paint drips on about 50–76%. Either the generator draws them like rust, or the verifiers can't tell them apart. Both are plausible without a human look.

## 11. Verifier hardening: v2 prompt with a look-alike checklist (overnight item 4, not adopted)

- **v2 prompt** (`backend/verify/verifier.py`, `SYSTEM_PROMPT_V2`) is v1 plus two additions:
  - an explicit look-alike checklist: paint and coatings, tape and labels, water stains, dirt, shadows, wood, reflections, copper;
  - a rule that an accept must name a **texture** cue (flaking, pitting, scaling, blistering, granular oxide, section loss, or a stain starting at a corroding part). It is stricter for box-proposed candidates.
- **Protocol (builder rules).**
  - Tune only on FLUX-tune: 188 synthetic look-alike candidates, one per image.
  - Evaluate on sets never used for tuning: the Muse Image stress set (486 Cloud candidates), the real public negatives (185 Cloud candidates), and the builder's audits (133 sure labels, 113 of them rust).
  - Adopt only if false alarms drop AND audited real-rust recall drops by no more than 3 points.
- Script: `benchmark/verifier_hardening.py`; results: `results/verifier_hardening_{tune,eval}.json`. Cost: Meta ≈ $2.3, Baseten ≈ $2.3. v1 verdicts were reused from earlier runs of the identical prompt.
- **Tuning gave no signal.** v1 and v2 both rejected all 188 FLUX-tune look-alikes. The FLUX images that render cleanly are easy. The hard cases (brown stains, drips, smudges) are exactly the categories FLUX draws as rust, so they could not be used.

| Verifier, prompt | Muse Image: candidates accepted | Real negatives: candidates accepted | Audited real-rust recall (95% CI) | Audited not-rust rejected |
|---|---|---|---|---|
| Hosted minimal, v1 | 281 / 486 | 41 / 185 | 97.3% (92.5–99.1) | 12 / 20 |
| Hosted minimal, v2 | 178 / 486 (−37%) | 21 / 185 (−49%) | 93.8% (87.8–97.0) | 13 / 20 |
| Muse Spark Open, v1 | – | 12 / 185 | 95.6% (90.1–98.1) | 13 / 20 |
| Muse Spark Open, v2 | – | 10 / 185 | 91.2% (84.5–95.1) | 14 / 20 |

- **Not adopted.** v2 roughly halves the false alarms of the demo verifier. But it costs 3.5 points of audited recall with the hosted verifier (110 → 106 of 113) and 4.4 points with Muse Spark Open, both over the 3-point limit. v1 stays the default.
- **Why no iteration.** Iterating the prompt on these evaluation sets would be tuning on them, which the protocol forbids, and FLUX-tune gives no signal. The trade-off is reported for the builder to decide.
- **Context.** Switching the Cloud verifier from minimal to low effort is the other lever: on the real negatives, 12.0% → 6.8% of images (§9), at a measured recall cost in the audits (§8).
