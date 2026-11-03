"""Demo data bundle: the sample walkdowns' frames and caches plus the finished examples, as one tarball.

The public demo server starts empty (Render's free filesystem is ephemeral) and downloads the bundle from a
PRIVATE Hugging Face dataset repo with HF_TOKEN, so no cache, frame or example ever lands in the public GitHub
repo. The bundle never holds the stock videos (Pexels License: no standalone redistribution): bundled clips
are extracted frames plus cached results (backend/agent/clip.py, "bundled").

    python -m backend.api.bundle pack G:/walkdown-data/deploy/walkdown-demo-bundle.tar.gz   # builder machine
    python -m backend.api.bundle fetch                                                      # container start
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import time
from pathlib import Path

from backend.api.samples import SAMPLES

DATA_DIR = Path(os.environ.get("WALKDOWN_DATA_DIR", "G:/walkdown-data"))
REPO = os.environ.get("DEMO_BUNDLE_REPO", "joshuakarthik2005/walkdown-demo-bundle")
FILENAME = os.environ.get("DEMO_BUNDLE_FILE", "walkdown-demo-bundle.tar.gz")
MARKER = ".bundle-ok"
# Never packed: stock videos and per-clip spend logs.
EXCLUDE_NAMES = {"source.mp4", "cost_ledger.jsonl"}
EXCLUDE_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4a", ".mp3", ".wav"}


def _members(data_dir: Path) -> list[tuple[Path, str]]:
    roots = [data_dir / "clips" / c for c in SAMPLES] + [data_dir / "examples", data_dir / "runs" / "decoded_masks"]
    out = []
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f"missing from the bundle source: {root}")
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.name not in EXCLUDE_NAMES and p.suffix.lower() not in EXCLUDE_SUFFIXES:
                out.append((p, p.relative_to(data_dir).as_posix()))
    return out


def pack(dest: Path, data_dir: Path = DATA_DIR) -> int:
    """Write the bundle tarball; returns the number of files."""
    members = _members(data_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        for path, name in members:
            tar.add(path, arcname=name, recursive=False)
    return len(members)


def fetch(data_dir: Path = DATA_DIR) -> bool:
    """Download and unpack the bundle into ``data_dir`` unless it is already there; False if it could not."""
    if (data_dir / MARKER).exists():
        return True
    local = os.environ.get("DEMO_BUNDLE_PATH")  # a local tarball instead of the download (container tests)
    token = os.environ.get("HF_TOKEN")
    if not token and not local:
        print("bundle: HF_TOKEN is not set; starting without samples or examples", file=sys.stderr)
        return False
    t0 = time.time()
    if local:
        path = local
    else:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(REPO, FILENAME, repo_type="dataset", token=token, cache_dir=data_dir / ".hf-cache")
    data_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "r:gz") as tar:
        tar.extractall(data_dir, filter="data")  # "data": no absolute paths, links or files outside data_dir
    if not local:
        Path(path).unlink(missing_ok=True)
    (data_dir / MARKER).write_text(str(time.time()), encoding="utf-8")
    print(f"bundle: unpacked {FILENAME} in {time.time() - t0:.1f} s", file=sys.stderr)
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pack").add_argument("dest", type=Path)
    sub.add_parser("fetch")
    args = ap.parse_args()
    if args.cmd == "pack":
        print(f"packed {pack(args.dest)} files into {args.dest}")
    else:
        try:
            fetch()
        except Exception as err:  # noqa: BLE001 - the API still starts (uploads work; samples and examples do not)
            print(f"bundle: download failed ({type(err).__name__}); starting without samples or examples",
                  file=sys.stderr)
