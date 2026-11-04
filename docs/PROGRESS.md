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

## 2026-10-27 — Phase 3/4/5 summary entries
- SAM test split scored (1,444 images, prompt "rust", $3.61): instance F1 0.34 at IoU 0.5; pixel precision 0.92, recall 0.36; image detection 65.6%. Written up in `benchmark/RESULTS.md` §1, including the granularity mismatch.
- Verifier dev dry runs (hosted and open), minimal-vs-low trial, agent loop, API, epsilon Pareto: see DECISIONS.md entries dated 2026-10-27.

## 2026-10-31 – 2026-11-01 — Experiments closed, voice note, final results
- Fireworks Serverless Training: Glimmer LoRA with images through a custom loop (the cookbook recipe is text-only); 208 steps, $0 training, $0.88 evaluation; audited recall 99.1%, same look-alike weakness as Modal (RESULTS 14).
- Glimmer v2 on Modal: clean-pipe images with an alarm 28 → 17, recall 99.1 → 94.7%; not adopted in On-prem mode (DECISIONS, 2026-11-01).
- F7: 50 / 50 live runs succeeded, 16 replans (RESULTS 15).
- SAM 3 full fine-tune: 9 attempts, three upstream training issues patched, NaN after ~300 steps at any learning rate or precision; negative result, ≈ $1.5 (RESULTS 18).
- F4 voice note: builder's 12 s recording transcribed and structured (P-401, LPG, coating damage near the flange, CUI check); shown in the UI under the register; cached by audio hash for the demo (RESULTS 19).
- COST_LOG final per-provider table (Meta and Modal from dashboards; Baseten and Fireworks from the ledger).
- README headline numbers and RESULTS summary updated; 108 tests pass.

## 2026-11-01 — Item 5 polish (moved up from Nov 3)
- Demo clips use a fixed frame grid (`fixed_sampling` in clip.json): three tank-farm runs gave an identical 24-entry register; clean-piping 0 entries; valve-tank 21 entries.
- Voice notes accept m4a/mp3/ogg/flac/webm (server-side PyAV decode); the builder's m4a hits the cached result.
- Bug fixed: the copilot and explain_plan now map a grouped defect to its work package (it answered "no assignment for W09").
- Fresh start: API ready in 2 s, UI first page 15 s. Click path timed in the browser; DEMO_SCRIPT.md rewritten with measured timings.
- Logged-out check: repo public, README and raw files return 200, no .env, audio, video or weights in the tree.

## 2026-11-02: public demo mode and judge-first UI

- **Demo mode** (`DEMO_MODE=true`):
  - samples use cached results only, and On-prem runs are switched off;
  - uploads are limited to 50 MB, 60 s and 20 photos;
  - per-IP hourly rate limits;
  - a global daily spend cap ($5 by default) charged by every paid call and persisted per UTC day;
  - friendly error messages throughout.
- **New endpoints:** `/samples` (credited Pexels clips with thumbnails), `/examples` and `/examples/{id}`. The finished examples are tank-farm (with the voice note and the crew-out replan), valve-tank and clean-piping. They load instantly as runs of their own.
- **Built the examples:** tank-farm 24 entries, OPTIMAL ($0.043); valve-tank 21 entries ($0.027); clean-piping 0 entries ($0.006). A first attempt with a broken clip loader cost about $0.03 and produced empty examples; I rebuilt them after the fix.
- **Bundled clips:** frames and caches without the source video, with `clip.json` "video" giving the duration.
- **UI v2:**
  - sample cards and "Open finished example" first, with upload as a drop zone;
  - one primary "Run the agent" button above the fold at 1080p;
  - a neutral Cloud / On-prem segmented control, and the asset form only for uploads;
  - shareable `?sample=`, `?example=` and `?run=` links that survive a refresh, with a fallback when the server no longer has the run;
  - polling backoff and a "stopped" state, plus friendly errors;
  - a one-line safety notice with the full disclosure expandable;
  - one headline metric (audited recall), with "What these numbers mean" expandable;
  - a "For judges" panel, logo and favicon;
  - the phone-width overflow fixed (tables scroll).
- **Checked in the browser:** the example loads, a refresh restores the run, an expired run falls back to the example, a live valve-tank sample run in the new UI (21 entries, OPTIMAL), a replan and a copilot question on a loaded example, and the production build. Screenshots are in `G:/walkdown-data/demo_checks/ui_v2/`.
- **Deployment:** skipped (DECISIONS 2026-11-02).
- **Tests:** test_demo.py, 10 tests.

## 2026-11-03: deployment prep (Render free + Vercel)

- **Memory:** the judge path in DEMO_MODE peaked at 512 MB. After the changes it peaks at 326 MB in a 512 MB / 0.1 CPU container. The changes:
  - bit-packed masks;
  - 2 CP-SAT workers;
  - a cap on runs held in memory;
  - streamed uploads;
  - early 413 for oversized bodies;
  - a 10 MB voice-note cap.
- **Container and bundle:**
  - `Dockerfile`, `render.yaml` and `requirements-demo.txt`;
  - `backend/api/bundle.py`, which packs and fetches the data bundle from a private HF dataset; examples were re-saved with packed masks;
  - `docs/DEPLOY.md` with the builder's click steps.
- **UI:** shows "Waking up the demo server (~1 min)…" when the first request takes more than 2.5 s.
- **Tests:** test_bundle.py (5 tests) and a test that oversized uploads are refused before reading.
- **Tests:** 126 pass. `test_planner_demo` failed twice earlier under CPU load, with and without these changes (FEASIBLE instead of OPTIMAL inside its time limit), then passed.

## 2026-11-03: public demo live

- **URLs:** UI https://walkdown-zeta.vercel.app/ (Vercel Hobby); API https://walkdown-lmnp.onrender.com (Render free, Docker). The data bundle is in the private HF dataset `joshuakarthik2005/walkdown-demo-bundle`. The builder created the accounts and entered the secrets.
- **Fixes found while deploying:**
  - Next.js moved to 15.5.28, because Vercel blocks vulnerable versions;
  - a trailing slash in `NEXT_PUBLIC_API_URL` is now dropped (it turned every path into `//path`);
  - CORS is now the outermost middleware, so the early 413 reaches the browser;
  - the UI checks file size before uploading.
- **Smoke test on the public URL (Chrome):**

  | Check | Result |
  |---|---|
  | Sample cards, thumbnails and credits | OK |
  | Tank-farm example | 24 entries, voice note, OPTIMAL plan, 8 frame overlays |
  | PDF / CSV | 200 (734 KB) / 200 (25 work orders) |
  | Replan in the UI | OPTIMAL |
  | Copilot question | answered |
  | Cached valve-tank sample run in the UI | 70 s, 21 entries, OPTIMAL |
  | On-prem run | 403 |
  | Voice note: wrong extension / 11 MB | 400 / 413 |
  | 55 MB upload | 413 |
  | Phone width (390 px iframe) | no sideways scroll |

- **Not tested on the public URL:** the waking notice after 15 minutes idle (it shows locally when the first request takes more than 2.5 s), and the spend-cap message (unit-tested; would need the live cap changed).

## 2026-11-04 · Final audit before the demo video

=== TASK REPORT ===
Task: Final audit (security, live product, code and build, numbers, credits, submission readiness)
Status: DONE (open items below are the builder's)
What I did: Scanned the repo and its full history for secrets (gitleaks: 159 commits, none). Tested every flow on the public demo at 1440 and 390 px, plus a fresh clone and a clean production build. Traced every headline number to its result file (docs/FINAL_AUDIT.md) and wrote the credit report (docs/CREDIT_USAGE.md).
Files changed: backend/api/app.py, frontend (DropZone, ForJudges, AgentTrail, PlanViews, page.tsx, lib/api.ts, package.json), tests/test_demo.py, tests/test_planner_*.py, README.md, THIRD_PARTY_NOTICES.md, benchmark/RESULTS.md, docs/DEMO_SCRIPT.md, docs/COST_LOG.md, docs/CREDIT_USAGE.md, docs/FINAL_AUDIT.md, docs/screenshots/, .gitignore, .env.example, ruff.toml, lint fixes in benchmark/ and modal_apps/
Commands run and results: pytest 128 passed; ruff (correctness rules) clean; tsc clean; next build clean in a fresh clone; pip-audit clean on all three requirement files; npm audit 0 vulnerabilities after a PostCSS override; mypy: 104 typing findings (not fixed, see Issues)
Tests: 128 passed (2 new tests: unreadable uploads, honest model-failure messages)
API usage this task: Meta ≈ $0.62 (public demo runs); Baseten, Fireworks and Modal $0
Running API total: see docs/CREDIT_USAGE.md (Meta $105.54 on the 2026-11-01 dashboard + ≈ $1.2 since)
Commit: 1e23a96, b04ddd7, a5de2a6, d627369, 3d7c533, 8c4b166, d385d1d and this one
Issues / risks: mypy is not part of the project; its 104 findings are mostly Optional narrowing and OpenAI SDK typing, left alone to avoid code changes right before filming. Render Auto-Deploy is on, so every push restarts the API. A Docker container on this machine also listens on port 8000, so record on 127.0.0.1:3000.
Next: the builder films the video and submits
===================
