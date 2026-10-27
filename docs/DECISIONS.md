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
