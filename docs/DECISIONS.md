# Design decisions

## 2026-10-27 — Python 3.12 for the virtual environment
The machine's default Python is 3.14.0, but 3.12.10 is also installed. The venv uses 3.12 because OR-Tools, OpenCV and pycocotools publish mature prebuilt wheels for it, which avoids build-from-source failures on Windows. It meets the 3.10+ target.

## 2026-10-27 — Pinned dependency versions
`requirements.txt` pins the exact versions that installed and imported cleanly, so the demo environment is reproducible.

## 2026-10-27 — `load_dotenv(override=True)` everywhere keys are loaded
A stale `MODEL_API_KEY` in the shell environment caused a 401: by default python-dotenv doesn't overwrite variables that already exist. Every key-loading call now passes `override=True`, so `.env` is always the single source of truth.

## 2026-10-27 — Set reasoning effort explicitly on every Muse Spark call
Per https://dev.meta.ai/docs/reasoning, reasoning tokens count toward `max_output_tokens` and are billed as output. When effort is omitted, the model picks its own level. In the first smoke test that used up the whole 200-token cap and returned an empty reply. All calls now set `reasoning={"effort": ...}`: `minimal` for trivial calls, `low`/`medium` for verification.
