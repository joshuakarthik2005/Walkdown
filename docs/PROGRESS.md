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
