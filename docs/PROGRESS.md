# Progress log

Task reports, appended after every task.

## 2026-10-27 — Phase 0.1: tool check, git init, first commit
- Status: PARTIAL (push blocked by local Claude Code permission rule; committed locally)
- Toolchain: Python 3.14.0 default, 3.12.10 also installed; Node v22.21.0; npm 10.9.4; git 2.51.1; gh installed but not logged in; Git Credential Manager configured.
- `.gitignore` created and staged before anything else; `git check-ignore` confirms `.env` is ignored.
- Commit: 6b364d6 Initial commit: gitignore, env example, README stub, MIT licence, build brief

## 2026-10-27 — Phase 0.2: virtual environment, requirements, folder layout
- Status: DONE
- `.venv` built on Python 3.12.10 (see DECISIONS.md). All requirements installed and pinned; import check passes, including `ortools.sat.python.cp_model`.
- Folder layout created: backend/{perception,verify,planner,agent,clients,api}, frontend, benchmark, docs, tests.

## 2026-10-27 — Phase 0.3: Meta API smoke test
- Status: BLOCKED
- `backend/clients/smoke_test.py` loads `.env` with python-dotenv, confirms which key names exist, and calls `muse-spark-1.3` via the Responses API, printing only reply and usage.
- `.env` loads; `MODEL_API_KEY` and `BASETEN_API_KEY` are both present. Key formatting checks (no quotes, no whitespace, no placeholder) pass without revealing the value.
- The call fails with `openai.AuthenticationError: Error code: 401 - Unauthorized`. Stopped per the brief; waiting for the builder to check the key on dev.meta.ai.

## 2026-10-27 — Phase 0.3 (resolved): Meta API smoke test
- Status: DONE
- Cause of the 401: a stale `MODEL_API_KEY` in the shell environment took precedence over `.env`. Fixed with `load_dotenv(..., override=True)`.
- Run 1 authenticated, but the reply was empty: reasoning used all 200 output tokens. Run 2 used `reasoning.effort=minimal` and `max_output_tokens=500`, and the reply was "Walkdown smoke test OK" (input 17, output 75 of which 61 were reasoning).
- Spend: $0.001211 total.

## 2026-10-27 — Phase 1.1: planner data model, config, time grid
- Status: DONE. Commit e288f61. Tests: 8 passed.
- Pydantic models for scenario, plan, explanation and change types; `PlannerConfig` holds all weights and solver settings. Time grid uses 1-hour slots (see DECISIONS.md).

## 2026-10-27 — Phase 1.2: scenario generator, plan evaluator and validator
- Status: DONE. Tests: 12 passed (4 new).
- `generator.py`: seeded synthetic scenarios (5 defect types mapped to skills/permits, permit types with lead times and concurrency caps, shutdown windows, crews covering every skill).
- `metrics.py`: `evaluate` (shared objective for every solver), `validate` (independent constraint checker), `crew_utilisation`, `moved_jobs`, `critical_unscheduled`.

## 2026-10-27 — Phase 1.3: CP-SAT solver
- Status: DONE. Tests: 18 passed.
- `cpsat.py`: optional intervals with element-constrained ends, crew no-overlap, permit cumulative caps, critical penalty, stability penalty for replanning, and fixed in-progress jobs. Time limit (default 10 s); reports status, objective, best bound, gap and wall time. The baseline is the default warm start, with an honest UNKNOWN fallback (see DECISIONS.md).
- `explain.py` (structured reasons) and `baseline.py` (priority sort, needed as the warm start) landed in the same commit; their own tests come in later tasks.

## 2026-10-27 — Phase 1.4: baseline comparison
- Status: DONE. Tests: 25 passed.
- `compare.py`: runs priority-sort and CP-SAT (warm-started from the baseline) on the same scenario. Reports risk-weighted exposure, criticals unscheduled, unscheduled count, crew utilisation (per crew and mean), solve time and gap.
- `test_cpsat_never_worse_than_baseline` is parametrised over seeds 0–5 (30 defects, 5 s limit).
- Found and fixed two solver issues along the way: an incomplete hint was being discarded, and presolve probing was starving the search (see DECISIONS.md).

## 2026-10-27 — Phase 1.5: replanning
- Status: DONE. Tests: 31 passed (6 new).
- `replan.py`: `apply_change` handles the three change types with validation, and `replan` returns a `ReplanResult` with moved jobs, newly scheduled/unscheduled jobs, and the objective before and after. Started work is fixed and moves are penalised. Baseline `keep_previous` mode is used as the replan warm start.
- Demo seed at now=40h, all OPTIMAL with zero violations:
  - busiest crew out 72h: 6 moved
  - SD1 cancelled: 9 moved, 1 crowded out
  - SD1 moved: 8 moved
  - new critical defect: 0 moved, and it is scheduled

## 2026-10-27 — Phase 1.6: explainability data
- Status: DONE. Tests: 37 passed (6 new).
- Tests cover every reason code path: permit lead time, shutdown wait, crew capacity naming the blocking job, crew leave, the four unscheduled causes plus crowded out, and work in progress after a replan. They also check that every defect is explained exactly once and that the plan serialises to JSON with string codes.

## 2026-10-27 — Phase 1.7: fixed demo scenario
- Status: DONE. Tests: 39 passed (2 new).
- Demo JSON saved. `python -m backend.planner.compare` prints the demo comparison: baseline 516,650 with 2 unscheduled; CP-SAT OPTIMAL 417,562 with 0 unscheduled, in 0.86 s, a 19.2% exposure reduction. Mean crew utilisation is 0.33 for the baseline and 0.36 for CP-SAT.

## 2026-10-27 — Phase 1 follow-up A: two-tier priority
- Status: DONE. Tests: 41 passed (2 new). Severity 5 is critical, severity 4 is high; both configurable.

## 2026-10-27 — Phase 2.3: impact sources (first pass)
- Status: PARTIAL. 6 figures verified from primary sources:
  - NACE IMPACT 2016: $2.5T, 3.4% of GDP, 15–35% savings, excludes safety and environmental costs
  - CSB Chevron Richmond 2012: 19 workers endangered, 15,000+ residents sought medical attention
  - Koch/FHWA: U.S. $276B, 3.1% of GDP; storage tanks $7B a year
- 5 candidates are listed but not usable: GAO and PHMSA pipeline-incident shares (sites block automated fetch), the CUI 40–60% figure (secondary sources only), HSE RR509 ageing, inspection effort.

## 2026-10-27 — Phase 2.4: shot list, evaluation metrics, split tooling
- Status: DONE (code). Tests: 7 new, passing. Real splits wait on the dataset download.
- `docs/DEMO_SHOT_LIST.md`: 5 clips (railings, pipe run, valves, tank, clean negatives), camera settings, privacy notes, licence statement, CC backup rules.
- `benchmark/seg_metrics.py`: mask IoU, greedy matching, precision/recall/F1, negative-image false-positive rate. `benchmark/splits.py`: stratified, seeded, disjoint dev/test file lists.

## 2026-10-27 — Phase 1 follow-up B: stratified planner benchmark and replan stability
- Status: PARTIAL. `benchmark/planner_benchmark.py` is written: 5 regimes (default, loose, tight_capacity, tight_shutdown, tight_permits), the static comparison, and a replan-stability comparison of CP-SAT vs baseline-from-scratch vs baseline-patch. The generator gained regime knobs; defaults are unchanged, and the demo reproducibility test passes.
- The full run was **stopped by Claude Code because the machine ran low on memory**. It got through all static runs and about 24 of 60 replan runs. Result files are written only at the end, so none exist. The numbers below are parsed from the console log and are unofficial:
  - static improvement over baseline, median (min–max):
    - default: 5.8% (0.3–19.2), n=19 parsed
    - loose: 3.5% (0.2–18.8)
    - tight_capacity: 2.7% (0.2–6.7), all FEASIBLE, none proven optimal
    - tight_shutdown: 1.0% (0.2–10.3)
    - tight_permits: 7.5% (1.5–24.9)
  - replan moved jobs, median CP-SAT / scratch / patch:
    - loose: 2/3/3 for crew out, 2/3/2 for window cancelled
    - tight_capacity: 15/16/3 for crew out, 18/13/2 for window cancelled, 12/15/0 for new critical
  - Finding: under tight capacity, CP-SAT replanning moves about as many jobs as re-running from scratch, far more than the baseline patch. The move penalty (200) is too weak there. A decision on this is needed.
- Not re-run: the session's rule is not to restart a job killed for memory pressure without being asked.

## 2026-10-27 — Phase 2.1/2.2: dataset download and splits
- Status: DONE, with a blocker on negatives. The dataset was downloaded via the Roboflow API (key from .env, never printed). valid/test are on G:. Licence and source are recorded in the README.
- Polygons confirmed. **Zero-annotation images: 0**, so negatives are 0% of test, below the 20% target. Reported, not invented.
- dev 50 / test 1,444, built over near-duplicate clusters with stock-style filenames excluded (215). See DECISIONS.md.

## 2026-10-27 — Phase 1 follow-up C: two-stage replan and full planner benchmark
- Status: DONE. Tests: 50 passed. The benchmark ran in the foreground, one regime at a time, with 4 workers: 10.8 min total, results saved per regime in `benchmark/results/`. The report is `benchmark/PLANNER_RESULTS.md`.
- Static, median risk improvement (min–max):
  - default: 5.8% (0.3–19.2)
  - loose: 3.5%
  - tight_capacity: 2.8%, all FEASIBLE, gap median 9.9%
  - tight_shutdown: 1.0%
  - tight_permits: 7.5% (1.5–24.9)
  - CP-SAT ≤ baseline on all 60 runs.
- Replan: CP-SAT moves fewer jobs than re-running the baseline from scratch in every regime/change cell. It still moves **more than the baseline patch in 8 of 12 cells** (e.g. tight_capacity crew out: 8 vs 4), with 1–41% lower risk than patch.
- Against scratch the risk difference is small, and sometimes slightly negative (down to −3.0% in single runs; median −0.6% for tight_shutdown/new_critical). This is because the 2% epsilon lets stage 2 give up a little risk for stability.
