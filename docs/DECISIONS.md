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
