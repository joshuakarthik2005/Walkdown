# Design decisions

## 2026-10-27 — Python 3.12 for the virtual environment
The machine's default Python is 3.14.0, but 3.12.10 is also installed. The venv uses 3.12 because OR-Tools, OpenCV and pycocotools publish mature prebuilt wheels for it, which avoids build-from-source failures on Windows. It meets the 3.10+ target.

## 2026-10-27 — Pinned dependency versions
`requirements.txt` pins the exact versions that installed and imported cleanly, so the demo environment is reproducible.
