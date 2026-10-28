"""Download the Roboflow corrosion segmentation dataset (COCO segmentation export).

Source: https://universe.roboflow.com/computervision-adpf6/corrosion-segmentation-xybsj
Licence (as listed on Roboflow Universe): Public Domain.

Reads ROBOFLOW_API_KEY from .env (never printed). Raw data goes outside the
repo, to WALKDOWN_DATA_DIR (default G:/walkdown-data), so it can never be committed.

    .venv\\Scripts\\python.exe -m benchmark.download_dataset info
    .venv\\Scripts\\python.exe -m benchmark.download_dataset download --version 1
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=True)
DATA_DIR = Path(os.environ.get("WALKDOWN_DATA_DIR", "G:/walkdown-data"))
RAW_DIR = DATA_DIR / "corrosion-segmentation-xybsj"
WORKSPACE = "computervision-adpf6"
PROJECT = "corrosion-segmentation-xybsj"
API = "https://api.roboflow.com"
EXPORT_FORMAT = "coco-segmentation"


def _key() -> str:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    key = os.environ.get("ROBOFLOW_API_KEY")
    if not key:
        raise SystemExit("ROBOFLOW_API_KEY missing from .env")
    return key


def _get_json(path: str) -> dict:
    url = f"{API}/{path}?api_key={_key()}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as err:  # never echo the URL: it contains the key
        raise SystemExit(f"Roboflow API error {err.code} for /{path}") from None


def info() -> dict:
    """Project metadata: versions, image counts, classes, licence (as reported by the API)."""
    data = _get_json(f"{WORKSPACE}/{PROJECT}")
    project = data.get("project", {})
    summary = {
        "name": project.get("name"),
        "type": project.get("type"),
        "images": project.get("images"),
        "classes": project.get("classes"),
        "license": project.get("license"),
        "versions": [
            {"id": v.get("id"), "images": v.get("images"), "splits": v.get("splits"),
             "exports": v.get("exports")}
            for v in data.get("versions", [])
        ],
    }
    print(json.dumps(summary, indent=1))
    return summary


KEEP_SPLITS = ("valid", "test")  # train holds Roboflow-augmented copies; not used for evaluation


def export_info(version: int) -> dict:
    """The export's metadata (signed link and reported size); does not download anything."""
    return _get_json(f"{WORKSPACE}/{PROJECT}/{version}/{EXPORT_FORMAT}").get("export", {})


def download(version: int, splits: tuple[str, ...] = KEEP_SPLITS) -> Path:
    """Request the COCO-segmentation export and unzip only ``splits`` into RAW_DIR.

    The train split (Roboflow augmentations) is used only for training, never for evaluation, and only
    after removing every near-duplicate cluster that touches dev or test (benchmark/train_pool.py).
    """
    export = export_info(version)
    link = export.get("link")
    if not link:
        raise SystemExit("export not ready; Roboflow may still be generating it, retry in a minute")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RAW_DIR / f"v{version}-{EXPORT_FORMAT}.zip"
    print(f"downloading export ({export.get('size', '?')} MB reported) ...", flush=True)
    urllib.request.urlretrieve(link, zip_path)  # signed link, not the API key
    with zipfile.ZipFile(zip_path) as z:
        keep = [m for m in z.namelist() if "/" in m and m.split("/")[0] in splits]
        for member in keep:
            target = (RAW_DIR / member).resolve()
            if RAW_DIR.resolve() not in target.parents and target != RAW_DIR.resolve():
                raise SystemExit(f"unsafe path in archive: {member}")
        z.extractall(RAW_DIR, members=keep)
    zip_path.unlink()
    print(f"extracted to {RAW_DIR}")
    return RAW_DIR


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "info":
        info()
    elif len(sys.argv) >= 2 and sys.argv[1] in ("download", "size"):
        v = int(sys.argv[sys.argv.index("--version") + 1]) if "--version" in sys.argv else 1
        if sys.argv[1] == "size":
            print(f"export size reported: {export_info(v).get('size', '?')} MB")
        else:
            splits = tuple(sys.argv[sys.argv.index("--splits") + 1].split(",")) if "--splits" in sys.argv else KEEP_SPLITS
            download(v, splits)
    else:
        print(__doc__)
