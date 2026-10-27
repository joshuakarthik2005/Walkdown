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
