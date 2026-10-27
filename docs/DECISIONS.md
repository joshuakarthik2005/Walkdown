# Design decisions

## 2026-10-27 — Python 3.12 for the virtual environment
The machine's default Python is 3.14.0, but 3.12.10 is also installed. The venv uses 3.12 because OR-Tools, OpenCV and pycocotools publish mature prebuilt wheels for it, which avoids build-from-source failures on Windows. It meets the 3.10+ target.

## 2026-10-27 — Pinned dependency versions
`requirements.txt` pins the exact versions that installed and imported cleanly, so the demo environment is reproducible.

## 2026-10-27 — `load_dotenv(override=True)` everywhere keys are loaded
A stale `MODEL_API_KEY` in the shell environment caused a 401: by default python-dotenv doesn't overwrite variables that already exist. Every key-loading call now passes `override=True`, so `.env` is always the single source of truth.

## 2026-10-27 — Set reasoning effort explicitly on every Muse Spark call
Per https://dev.meta.ai/docs/reasoning, reasoning tokens count toward `max_output_tokens` and are billed as output. When effort is omitted, the model picks its own level. In the first smoke test that used up the whole 200-token cap and returned an empty reply. All calls now set `reasoning={"effort": ...}`: `minimal` for trivial calls, `low`/`medium` for verification.

## 2026-10-27 — Planner time model: 1-hour slots, wall-clock grid
- Time is a grid of 1-hour slots. Hour 0 is midnight at the start of day 0, and the horizon is `horizon_days × 24` hours (default 14 days = 336 slots).
- Each crew works one shift a day, 08:00–16:00 by default. Start, length and work days are configurable. Shifts may not cross midnight.
- A job needs `repair_hours` on-shift hours from one crew. A job longer than the hours left in a shift pauses overnight and resumes at the next shift, so its wall-clock interval `[start, end)` can span nights. Crews are idle off-shift anyway, so a crew-level no-overlap on wall-clock intervals is correct.
- A job may not overlap a crew unavailability period. A shutdown-only job must sit entirely inside one shutdown window. Work can't start before the permit is ready (`found_at + lead_hours`).
- Why 1-hour slots on a wall-clock grid: exposure ("risk × hours until repair completes") is naturally a wall-clock quantity, since a defect keeps deteriorating at night. One hour is fine enough for repair estimates, which are given in whole hours, and keeps the model small: 336 slots, with feasible starts precomputed per (defect, crew) as a table.

## 2026-10-27 — CP-SAT formulation
- One option per (defect, eligible crew): a presence literal, a start variable whose domain is only the precomputed feasible starts (on shift, after release, inside a shutdown window if needed, clear of crew leave), and an end tied to the start by an element constraint over the wall-clock end table. Optional intervals go into a no-overlap per crew, and into a cumulative per permit type that has a concurrency cap. Each defect takes exactly one option or an "unscheduled" literal.
- The objective is `Σ risk_weight × (completion − found_at)`, with completion = horizon end when unscheduled, plus `critical_penalty` per unscheduled critical defect, plus `move_penalty` per moved job when replanning. `risk_weight = round(risk_scale × failure_risk × severity_weight[severity])`. All weights live in `PlannerConfig`.
- The same objective is computed independently by `metrics.evaluate` for every solver. Tests assert the CP-SAT objective equals it, and `metrics.validate` independently checks every constraint.

## 2026-10-27 — Baseline warm start and honest UNKNOWN fallback
- What I saw: on a 40-defect scenario, CP-SAT presolve (probing) took 2–6.6 s, varying between runs. With a 1–5 s limit it sometimes returned UNKNOWN, meaning no solution at all.
- Decision: `solve` passes the priority-sort plan to CP-SAT as a solution hint by default. If CP-SAT still has no solution when the limit expires, it returns the warm-start plan with `status="UNKNOWN"` and `fallback="warm_start"`, no bound and no gap. Such a result is never reported as a CP-SAT solution, and FEASIBLE is never reported as optimal (`SolveStats.is_optimal` is true only for OPTIMAL).
- With the 10 s default, the 40-defect case reaches FEASIBLE with objective 1.31–1.39M against the baseline's 2.50M. The gap to the bound is still large: the LP bound is weak for this model, and that will be reported as-is in the benchmark.

## 2026-10-27 — Complete solution hint, and CP-SAT probing level 0
- What I saw: on seed 5 (30 defects), CP-SAT returned a plan *worse* than its baseline hint (2.10M vs 0.49M). Fixing the variables to the hint gave 490,579, which equals the baseline, so the hint was feasible. It was just incomplete (126 of 233 variables), and CP-SAT dropped it. The fix is to hint every variable: absent options, spans, completions, stability literals.
- Presolve probing took most of the 5 s budget on some seeds (status UNKNOWN). Measured on seeds 0–5, 30 defects, 5 s limit, improvement over baseline:

  | probing | 0 | 1 | 2 | 3 | 4 | 5 |
  |---|---|---|---|---|---|---|
  | default (2) | 5.5% | UNKNOWN | 2.5% | 5.3% OPT | UNKNOWN | 0.9% |
  | 1 | 2.4% | UNKNOWN | 1.1% | 5.3% OPT | UNKNOWN | 0.9% |
  | 0 | 6.1% | 60.6% | 5.6% | 5.3% OPT | 0.9% | 9.6% |

  `PlannerConfig.probing_level` now defaults to 0.

## 2026-10-27 — Replanning semantics
- A job is "started" when its start is earlier than `now`. Started jobs are fixed: same crew, same times. They are exempt from new constraints, so an in-progress job finishes even if its crew is later marked unavailable or its shutdown window is cancelled. The alternative, abandoning half-done work, isn't modelled.
- Every other previously planned job may move, at `move_penalty` (default 200) per moved job. A job counts as moved if its crew or start changed, or it was dropped. 200 is about one hour of exposure for a mid-risk defect, so CP-SAT moves a job only for a real risk gain. Setting the penalty to 0 or very high is tested.
- New defects get `found_at = now`, so their permit lead time counts from discovery and exposure counts from when they were found.
- The replan warm start is `priority_sort(keep_previous=True)`: keep every still-feasible planned job, then fill the gaps greedily. It's the usual manual "patch the schedule" response, and it gives CP-SAT a stable starting point.
- Change types: `CrewUnavailable(crew_id, start, end)`; `ShutdownWindowChanged(window_id, new_start, new_end)`, which cancels the window when both are omitted; `NewDefect(defect)`. Changes chain: each replan returns the changed scenario and new plan, ready for the next one.

## 2026-10-27 — Structured plan explanations
- Each defect gets a `DefectExplanation` with status (scheduled, unscheduled, in_progress, completed), crew, times, release hour, earliest feasible start, and a list of `Reason{code, delay_hours, until_hour, related_ids}`. No prose: Muse Spark narrates it later. Keeping it structured means the narration can be checked against the data, so a grade or claim the data doesn't support can be caught.
- How delay is attributed: the feasible-slot search is re-run with filters switched on one at a time, in a fixed order: permit release, then shift hours, then shutdown window, then crew leave. Each step that pushes the earliest start later becomes a reason with that delay. Any remaining delay between the earliest feasible start and the actual start is attributed to capacity: CREW_CAPACITY, naming the jobs on eligible crews in that gap, and/or PERMIT_CONCURRENCY. If no job is in the way, it is DEFERRED_BY_OPTIMISER (e.g. kept in place by the move penalty).
- For unscheduled defects, the first filter that leaves no feasible slot is reported (NO_SKILLED_CREW, DOES_NOT_FIT_IN_HORIZON, PERMIT_NOT_READY_IN_HORIZON, NO_SHUTDOWN_WINDOW_FITS, CREW_UNAVAILABLE). If slots exist, the reason is CROWDED_OUT.
- Limitation: attribution follows a fixed order. When two filters overlap, the earlier one in the order gets the credit.

## 2026-10-27 — Fixed demo scenario
- `backend/planner/scenarios/demo_scenario.json`: 25 defects, 4 crews, 2 shutdown windows, 14-day horizon. Generated by `python -m backend.planner.generator` from seed 13. The committed JSON is the demo's source of truth, and a test checks that it still matches the generator.
- Seed 13 was **picked** from seeds 0–19 because it solves to OPTIMAL quickly and tells a clear story: the priority sort leaves 2 defects unrepaired, while CP-SAT schedules all 25 with 19.2% less risk-weighted exposure. It is not a representative result. The benchmark (Phase 7) reports all seeds; at 10 s on seeds 0–19 the improvement ranged from 0.3% to 19.2%.

## 2026-10-27 — Two-tier unscheduled penalty (builder decision)
- Severity 5 is **critical** (`critical_penalty`, default 1,000,000 per unscheduled defect). Severity 4 is **high** (`high_penalty`, default 100,000). Both thresholds and penalties are in `PlannerConfig`.
- High is ten times smaller than critical, so a critical job always wins a scarce slot over a high one. It is still larger than the exposure of any single defect over the 14-day horizon (at most 100 × 1.0 × 8 × 336 ≈ 269k for severity 4), so a high job beats any lower-severity job, as the test for this shows.
- Plans now report `high_unscheduled` alongside `critical_unscheduled`, and the breakdown has a separate `high_penalty` term.

## 2026-10-27 — Segmentation evaluation protocol
- Instance-level matching: greedy and one-to-one, in descending prediction score, at IoU ≥ 0.5 (configurable). Mask IoU via pycocotools RLE. Precision, recall and F1 are computed over all instances in the split. Mean IoU is over matched pairs only.
- Negative images (no ground-truth instance) are counted separately: the share of negatives with any false positive, and the total false positives on negatives. These are the main numbers for the verifier, whose job is to reject false positives.
- Splits: one fixed seed (20261027). The dev split (~50 images) is for dry runs and prompt tuning; the held-out test split (1,000–2,000) is never used for tuning. Both are stratified by positive/negative, disjoint, and saved as sorted text lists in `benchmark/splits/`.

## 2026-10-27 — Dataset, storage and splits
- Dataset: Roboflow `computervision-adpf6/corrosion-segmentation-xybsj` v1. The Roboflow API and the export README both say "License: Public Domain". Annotations are instance polygons: 13,193 in valid+test, all polygons, one class.
- Raw data lives **outside the repo** at `WALKDOWN_DATA_DIR`, default `G:/walkdown-data`. Drive C: filled up during the first extraction; the partial copy was deleted with the builder's approval and the data moved to G: at the builder's request.
- Only `valid` (1,024) and `test` (1,026) are used. `train` (14,214) contains Roboflow augmentations of 6,788 source images, and near-duplicates would leak into evaluation.
- Near-duplicates: valid+test are themselves merged from several sources. Of 2,050 images, 1,807 are distinct at an exact difference hash, and 1,664 at ≤10 differing bits. Filenames are not usable for dedup: generic names like `000226_jpg` collide across sources while the images differ. Splits are built over dHash clusters (≤10 bits), one image per cluster, so dev and test never share a near-duplicate.
- Rights: 215 images have commercial-stock-style original filenames (Adobe Stock `1000_F_<id>`, `istockphoto-…`, Alamy-style ids). The uploader's Public Domain label may not cover them, so they are excluded from both splits and never sent to an API.
- **No negatives**: 0 of 2,050 images have zero annotations. The test split is 100% positive. Negatives were not invented; the builder decides where they come from.
- Result: dev 50 images (320 instances), test 1,444 images (9,812 instances), seed 20261027. `benchmark/splits/manifest.json` has every count.

## 2026-10-27 — Rule: dataset images are for scoring only, never for public material (builder decision)
- The 1,494 filtered Roboflow images (and every other dataset image) are used **only for benchmark scoring**. They must never appear in the README, the demo video, UI screenshots, X posts, slides or any other public material. Their provenance can't be fully verified (see "Dataset, storage and splits").
- Every public visual comes from the builder's own footage and photos.
- Practical consequences: the demo path and cached demo results use the builder's clips only. Benchmark reports show numbers and charts, never sample images. Any debugging overlays of dataset images stay under `WALKDOWN_DATA_DIR` (outside the repo).

## 2026-10-27 — Negatives set from the builder's own footage
- `benchmark/build_negatives.py`: frames at ~1 fps from the builder's clips, plus photos, resized to 640 px on the long side, deduplicated with the same dHash clustering (≤10 bits). Stored under `WALKDOWN_DATA_DIR/negatives/frames`.
- Every frame from one source file goes to the same split, to avoid leakage between near-identical frames. About 10 go to dev; test is capped so negatives are ~20% of test (≈361 for 1,444 positives). File lists are `benchmark/splits/negatives_{dev,test}.txt`, with `negatives_manifest.json`.
- The positive splits are unchanged, so the negatives are an additional, separately reported set: false-positive rate on negatives.

## 2026-10-27 — Caches on G:
- C: is nearly full. pip cache is at `G:\walkdown-cache\pip` (user pip.ini and PIP_CACHE_DIR), npm cache at `G:\walkdown-cache\npm`, and HF_HOME at `G:\walkdown-cache\hf`. Datasets live in `G:\walkdown-data`. No large files go on C:.

## 2026-10-27 — Two-stage (lexicographic) replan instead of a move penalty (builder decision)
- Why: in the interrupted benchmark, with a 200 move penalty, CP-SAT replans under tight capacity moved about as many jobs as re-running from scratch (median 15 vs 16) and far more than the baseline patch (3).
- Now, when replanning with previously planned work, the solve runs in two stages:
  1. Minimise risk (exposure + critical/high penalties). Gets `stage1_time_share` = 60% of the time limit.
  2. Add `risk ≤ stage-1 value × (1 + replan_epsilon)`, with epsilon 0.02, and minimise `move_job_weight × moved jobs + hours displaced` (weight 24, i.e. one moved job ≈ one day of displacement; a dropped job counts as displaced to the horizon end). Warm-started from the stage-1 solution with every variable hinted. Gets the rest of the time.
- If stage 2 finds nothing better, the stage-1 plan stands.
- Reporting:
  - `stats.stages` lists both stages.
  - Overall status is OPTIMAL only if both stages are OPTIMAL.
  - `stats.objective` is the final plan's risk objective. `best_bound` and `gap` are stage 1's.
- Caveat: epsilon is relative to the stage-1 value *found*. If stage 1 is FEASIBLE rather than OPTIMAL, the stage-2 cap is relative to a sub-optimal risk value.
- The single-stage move penalty is still available (`lexicographic_replan=False`) for comparison.
- First check (tight capacity, 45 defects, 3 crews, busiest crew out 72 h, seeds 0–1):
  - two-stage moved 8 and 7 jobs; baseline patch moved 4 and 5
  - two-stage risk was 11.6% and 2.8% lower than patch
  - churn dropped (from ~15), but is still higher than patch

## 2026-10-27 — SAM 3.1 client
- Request format follows https://dev.meta.ai/docs/sam/segmenting: Responses API, `model="sam-3.1"`, one user message with `input_text` (a noun-phrase concept) and `input_image` (a base64 data URL) or `input_video` (a Files API `file_id`). `metadata.include_confidence="true"`.
- Output is parsed with Meta's own `meta-sam-parser` 0.1.0 (SAM License, Meta Platforms). Each mask is a box-local raster exactly the size of its box; it is pasted at (left, top) into a full-frame boolean mask.
- Billing comes from `usage.images_processed` and `usage.video_frames_processed`. Token counts are 0 for SAM. Each call is recorded in a `CostLedger`.
- Retries: exponential backoff on 429, 5xx, timeouts and connection errors. Auth, permission and 402 errors raise `BillingError` immediately: stop and report, per the brief.
- Video: clips are re-encoded to `sample_fps` (default 2) before upload, so only sampled frames are billed (minimum 50 per request). **Unverified**: on a synthetic clip the request completes and is billed but returns no detections, in both MPEG-4 and H.264, while the same frame sent as an image matches. To be re-tested on the builder's real footage.
- An empty output means "no match" (per the docs). The synthetic "rust" plate is not recognised as rust, so parser fixtures use the concept "circle".

## 2026-10-27 — SAM prompt choice from the dev dry run
- 50 dev images (320 ground-truth instances, 6.4 per image; 24% of instances are under 500 px), IoU ≥ 0.5, instance level:

  | Prompt | Precision | Recall | F1 | Matched IoU | Pixel IoU | Preds/img |
  |---|---|---|---|---|---|---|
  | rust | 0.45 | 0.33 | 0.38 | 0.82 | 0.51 | 4.7 |
  | corrosion | 0.57 | 0.27 | 0.37 | 0.83 | 0.41 | 3.0 |
  | corroded metal | 0.37 | 0.06 | 0.10 | 0.83 | 0.30 | 1.0 |

- **Chosen: "rust"**. It has the best recall and pixel IoU, and F1 equal to the best. In Walkdown, SAM proposes candidates and Muse Spark rejects false positives, so SAM's recall matters more than its precision. "corroded metal" tends to segment the whole object as one instance.
- Combining "rust" with "corrosion" (deduplicated at mask IoU 0.5) gives exactly the same scores as "rust" alone: the "corrosion" masks duplicate "rust" masks. So a second prompt doubles the cost for nothing.
- SAM returns no detection below confidence ~0.5 (minimum seen 0.504). Thresholds of 0, 0.3 and 0.5 are identical, and 0.7 trades recall for precision (rust: P 0.75, R 0.17).
- Caveat: recall is limited partly by annotation granularity. The ground truth splits rust into many small patches, while SAM returns fewer, larger regions. Matched IoU (0.82) shows that what SAM does match, it segments well. Pixel IoU is reported alongside for that reason.

## 2026-10-27 — Verifier design (Phase 4)
- Input per candidate: a tight crop around the mask's box with 30% margin (at least 64 px), the mask outlined in cyan, scaled to 448 px; plus a 256 px full-frame thumbnail with the box drawn. Text gives the SAM confidence, the mask's share of the frame, and the box.
- Output schema: `is_defect`, `defect_type` (enum), `severity` 1–5, `confidence`, `evidence` {visual_cues, location, extent, mask_fit}, `recommended_action` (enum). Validated with Pydantic, plus rule-based consistency flags for human review.
- Meta (hosted `muse-spark-1.3`): Chat Completions, `response_format` json_schema with `strict: true`, `reasoning_effort="low"`, `max_tokens=4000`, `prompt_cache_key`. Chat Completions is used because it is the form the Meta structured-output docs actually show. The fixed system prompt comes first, so it is cached automatically: 612 of ~990 input tokens were cached on average.
- Baseten (`meta-models/muse-spark-open-1026`): Baseten's docs say structured outputs are offered for all Model APIs *except* Muse Spark Open, so the schema goes in the prompt and replies are validated with Pydantic (one retry on invalid JSON). `reasoning_effort` is not documented for it and is not sent.
- If a reply is invalid, the candidate is accepted ("fail open") and flagged `no_valid_grade`. Better to show a candidate for review than to silently drop a possible defect.

## 2026-10-27 — Verifier ground truth (rule)
- For each SAM candidate, `coverage = |candidate ∩ union of GT masks| / |candidate|`. **TP if coverage ≥ 0.5, FP if coverage < 0.1, ambiguous otherwise.** Ambiguous candidates are verified and counted, but left out of the classifier metrics.
- Why coverage rather than instance IoU: the annotations split rust into many small patches while SAM returns larger regions, so a correct SAM region covering several annotated patches would fail an IoU ≥ 0.5 match.
- **Caveat found in the dev dry run:** a private visual check of labelled-FP crops (kept on G:, never published) showed that several "FPs" are visible rust or rust staining that the dataset didn't annotate. On this dataset the FP labels are partly annotation gaps, not true negatives. FP-rejection numbers from it are therefore a lower bound on usefulness and **not** a reliable estimate. The negatives set from the builder's own footage is the real test of false-positive rejection.

## 2026-10-27 — Severity: consistency, not accuracy
- There is no severity ground truth, so no severity accuracy is claimed. Consistency is measured instead: 30 candidates are graded twice with identical requests, and agreement on is_defect, defect_type, exact severity and severity ±1 is reported. Cross-provider agreement (hosted vs open) is reported too.

## 2026-10-27 — Stability vs risk setting (epsilon) and its Pareto points
- `replan(..., epsilon=…)` exposes the two-stage epsilon as a "stability vs risk" setting for the planner API (and later the UI).
- Demo scenario, change at hour 48 (`benchmark/results/replan_pareto_demo.json`), all OPTIMAL:

  | Change | ε | Jobs moved | Hours displaced | Exposure |
  |---|---|---|---|---|
  | busiest crew out 72 h | 0.00 | 7 | 476 | 560,332 |
  | | 0.02 | 6 | 474 | 560,796 |
  | | 0.05 | 6 | 474 | 569,328 |
  | | 0.10 | 6 | 474 | 560,796 |
  | first shutdown window cancelled | 0.00 | 12 | 1,300 | 712,150 |
  | | 0.02 | 9 | 1,143 | 728,262 |
  | | 0.05 | 7 | 1,094 | 749,126 |
  | | 0.10 | 7 | 1,094 | 749,126 |

- Known gap: stage 2 minimises churn only, so among equally stable plans it doesn't prefer the lower-risk one. That's why ε 0.05 shows higher exposure than ε 0.10 for the crew-out case. A tie-break (a small risk term in stage 2, or a third stage) would fix it; deferred.

## 2026-10-27 — Verifier effort: minimal for the live demo, low for the benchmark (builder rule)
- Same 50 dev candidates, minimal vs low:
  - is_defect agreement 94% (47/50). All 3 disagreements are on dataset-labelled FPs: minimal accepted 2 that low rejected, and rejected 1 that low accepted.
  - TPs wrongly rejected: 0 for both. Invalid replies: 0 for both.
  - Severity agreement: 81% exact, 100% within ±1.
  - Cost per candidate: $0.0024 vs $0.0043. Reasoning tokens: 300 vs 743. Median latency: 5.7 s vs 6.3 s.
- Under the builder's rule (match on is_defect agreement and TP rejections), minimal is used in the live agent path. API default: `verify_effort="minimal"`. The benchmark stays on low.

## 2026-10-27 — Agent loop (Phase 5)
- Muse Spark (`muse-spark-1.3`, reasoning low) with Chat Completions tool calling, following the Meta tool-calling docs: tools under `function`, `tool_choice` left at auto (the only supported value), the assistant message with `tool_calls` appended before one `tool` message per call.
- The six tools work on an `AgentSession`: segment_frames, verify_candidate, build_register, plan_maintenance, replan(change, now_hour, epsilon), explain_plan. The model only ever sees compact summaries (ids, boxes, grades, plan stats, structured reasons), never masks or images.
- `explain_plan` returns the planner's own structured reasons. The system prompt says every reason must come from those codes.
- SAM outputs and verdicts are cached per clip and frame on G:. `live=True` ignores the cache. A cached demo run makes no SAM or verifier calls.
- Each model turn and tool call becomes a `TraceEvent`: kind, name, args, summary, result, start, duration, tokens, cost. Tool errors go back to the model as `{"error": …}`, so it can recover. In the dry run it fixed its own malformed `replan` call. The change format is now normalised to tolerate nesting, too.
- Verification inside the tool runs 8 candidates in parallel. The sequential first version took 188 s for 20 candidates.

## 2026-10-27 — Register to planner mapping (rules, not model output)
- Detections are merged into one register entry when, within ≤2 sampled frames, their box IoU is ≥0.3. Photo clips are never merged. The entry keeps its most severe grade.
- skill / permit:
  - leak_stain → mechanical / cold_work
  - damaged_insulation → insulation
  - severity ≥4, or action repair/replace → welding / hot_work
  - otherwise → coating
  - a tank with severity ≥4 needs confined_space
- needs_shutdown: severity ≥4 on a pressurised asset, or any leak stain.
- repair_hours by severity: 2 / 3 / 6 / 10 / 12.
- failure_risk = base risk by severity (0.05 / 0.15 / 0.35 / 0.6 / 0.85) × (0.5 + 0.5 × verifier confidence), capped at 0.95.
- found_at = the session's current hour.
- These are placeholder engineering rules for the demo, stated openly, not calibrated values.

## 2026-10-27 — Demo solver limit and capacity explanations (builder decision)
- The demo path (`AgentSession`) gives each solve 30 s instead of 10 s. The first dry-run plan, with 52 defects, was FEASIBLE rather than OPTIMAL at 10 s. Status and gap are always reported, and the agent prompt forbids calling a FEASIBLE plan optimal.
- Crowded-out defects now carry the crew-hour arithmetic in `Reason.detail`: skill, eligible crews, skilled hours from release to horizon, hours booked, hours free, and the job's repair hours. There is also a one-line summary ("not enough coating crew hours in the horizon: …"). The agent is told to say this plainly, using those numbers.

## 2026-10-27 — Measured server-side throughput cap for the verifier; the demo path stays cached
- Measured on the full test-split verifier run (hosted `muse-spark-1.3`, reasoning low, 2 images per call):
  - Throughput plateaus at **~16–17 verifier calls per minute** for this account, whatever the concurrency. 8 and 32 concurrent calls gave the same throughput; at 32 the median latency rose to 48 s (p90 136 s), at 8 it was 18.5 s.
  - An isolated call takes 8–10 s.
  - Rate-limit headers show no pressure (2,998 of 3,000 RPM left, tokens untouched), and no 429s were seen. This is undocumented queueing on the server side, not our rate limit.
- Consequences:
  - The full run uses 8 concurrent calls (4 processes × 2 threads). More concurrency only adds latency.
  - It is supervised and restarts from cache automatically (`benchmark/verify_supervisor.py`).
  - **The live demo must use cached perception and verification results.** At this cap, a 30-frame clip with ~100 candidates would take 6+ minutes of verifier time live. Live mode stays available behind the `live` flag, and the trace shows its real timing.

## 2026-10-27 — Correction: the "~16–17 calls/min throughput cap" was not a stable cap
- The earlier entry described a server-side cap of ~16–17 verifier calls/min. Over the rest of the run, the same 8-concurrent setup reached **74 calls/min** in its final clean chunk, with a run-wide median latency of 5.3 s (p90 25.9 s).
- The early low throughput was a mix of: a temporary period of high API latency; this benchmark's own chunk crashes (an unpicklable `APIConnectionError` broke the process pool; fixed in d1c3a43); and pure-Python mask decoding.
- Correct statement: Meta API latency and throughput varied by ~4× over a few hours, with no 429s. The decision that the demo path uses cached perception and verification stands, for this reason.

## 2026-10-27 — Line-service consequence weighting (builder decision)
- Planner risk per hour unrepaired = `risk_scale × likelihood × consequence`.
  - likelihood = `failure_risk × severity_weight[severity]` (unchanged).
  - consequence = a per-service factor of the asset's line service. `None` (unknown) means 1.0, so synthetic benchmarks and the demo backlog are unaffected.
- **Default consequence factors are ASSUMPTIONS chosen by judgement for the demo, not industry figures:**
  - hydrogen 3.0, LPG 3.0: flammable gases with wide flammability ranges, high escalation potential
  - hydrocarbon vapour 2.5
  - crude 2.0, chemical 2.0
  - steam 1.5: burn hazard to people
  - fire water 1.5: failure impairs a safety system
  - cooling water 1.0
  - air/nitrogen 0.8
  They are configurable per site in `PlannerConfig.consequence_factor`. A real deployment should take them from the site's own risk-based-inspection consequence ranking.
- The service is set per asset at upload time (`service` form field). It flows into the register and into every planner defect. Each plan explanation carries `priority` = {service, severity, likelihood, consequence_factor, risk_weight, critical, high}, and the agent is told to use it when explaining why one job outranks another.

## 2026-10-27 — Product framing (builder decision)
- Walkdown is for **plant and facility walkdowns**: refineries, tank farms, terminals, pump and compressor stations, power plants.
- Long cross-country pipelines are inspected with in-line inspection tools; Walkdown complements them on unpiggable plant piping and equipment.
- Footage is handheld today. Drone and robot footage is future scope and is not claimed to work.
- The same framing is used in the README, the UI copy and the video script. Earlier wording ("energy plant (pipelines, …)") was replaced.

## 2026-10-28 — Demo plan quality: why the gap was large, what was tried, and the demo sizing
- **Before:** the demo case (25-job backlog + 27 walkdown defects from the dev pseudo-clip) ended FEASIBLE at 30 s with a 33–39% gap. That held for backlogs of 10, 15 or 25 jobs and for 4 or 12 workers. Even 25 + 4 walkdown defects left a 13.7% gap (10.1% at 120 s).
- **Diagnosis:** the incumbent objective does not improve between 30 s and 120 s, so the plan is very likely near-optimal and the **lower bound is what's weak**. Removing permits, shutdown windows or the unscheduled penalties left a 16–22% gap. The cause is intrinsic: weighted completion time with release dates on a busy crew (strongly NP-hard), where LP bounds are weak.
- **Tried and rejected:**
  - CP-SAT `linearization_level=2`: gap 38.7%.
  - Adding `optimize_with_lb_tree_search`: 53.6%.
  - A working-hour-timeline reformulation (fixed-size intervals per crew, plus a valid linear cut linking wall-clock and working-hour completion). It was exact and passed all tests, but gave no bound gain and made the 25-job backlog 9× slower (0.9 s → 7.7 s). Reverted.
- **Kept:**
  - All CPU cores by default (`PlannerConfig.num_workers = os.cpu_count()`; benchmarks still pin 4 for comparability).
  - Symmetry breaking for interchangeable crews (same skills, shift, calendar, no leave): booked hours ordered, and the warm start relabelled to match. Only applied without fixed or previously planned work.
  - The baseline warm start with every variable hinted (already in place).
- **Demo sizing (measured, 30 s limit):**
  - backlog 12 + 3 or 6 walkdown defects: OPTIMAL in 1.2 s / 5.9 s
  - backlog 16 + 6: OPTIMAL in 19 s
  - backlog 12 + 8: FEASIBLE, gap 7.6%
  - backlog 12 + 10: FEASIBLE, gap 10.2%
  - replans on 12 + 6 (crew out, shutdown cancelled): OPTIMAL in < 2 s
  - So the demo backlog is the first **12 jobs** of the demo scenario (`backend.agent.tools.demo_backlog`), and the demo clip should yield **≤ 6 register defects**. Above that the badge honestly shows FEASIBLE with the gap.
- A replan with ε = 0.02 can show "OPTIMAL, gap 2.0%". That is by design: both stages are optimal, and stage 2 may give back up to ε of risk for stability, measured against the stage-1 bound.
