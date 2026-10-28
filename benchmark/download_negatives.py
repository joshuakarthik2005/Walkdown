"""Public negatives: rights-cleared images of non-corroded metal, for the false-positive test only.

Fallback while the builder's own negatives footage is pending. Results on these sets are always reported
separately from the builder's footage. The images are used only for scoring, never in public material and never
for training (a training-negatives subset would have to be split off before any FP test).

Sources (licence as reported by the Roboflow API on 2026-10-28; attribution in docs/FOOTAGE_SOURCES.md):
- corrosion-detection-sd/non-corroded-pipe (classification, CC BY 4.0): class "Non-Corroded";
- corrosion-detection-sd/corrosion-detection-1 (classification, CC BY 4.0): class "Non-Corroded-1" only.

Roboflow train splits hold augmented copies (flip, ±15° rotation, crop, blur: 3 versions per source), which a
dHash does not catch, so images are first grouped by Roboflow source name (``<source>.rf.<hash>``), keeping one per
source. The two projects share an uploader, so the survivors are then deduplicated with 256-bit dHash under the
8 flips/rotations (<= 40 bits = duplicate, the threshold measured in benchmark/train_pool.py).

    .venv\\Scripts\\python.exe -m benchmark.download_negatives
"""

from __future__ import annotations

import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from benchmark.download_dataset import DATA_DIR, _get_json
from benchmark.train_pool import ANY_BITS, POPCOUNT, dhash_variants

OUT = DATA_DIR / "negatives_public"
SOURCES = [
    dict(project="corrosion-detection-sd/non-corroded-pipe", version=1, classes=["Non-Corroded"]),
    dict(project="corrosion-detection-sd/corrosion-detection-1", version=1, classes=["Non-Corroded-1"]),
]
FORMAT = "folder"
MANIFEST = Path(__file__).parent / "results" / "negatives_public_manifest.json"


def fetch(src: dict) -> list[Path]:
    """Download one export and return the images of the wanted classes (all splits)."""
    name = src["project"].replace("/", "__")
    dest = OUT / "raw" / name
    if not dest.exists():
        meta = _get_json(f"{src['project']}/{src['version']}/{FORMAT}").get("export", {})
        if not meta.get("link"):
            raise SystemExit(f"export of {src['project']} not ready; retry in a minute")
        dest.mkdir(parents=True)
        zip_path = dest / "export.zip"
        urllib.request.urlretrieve(meta["link"], zip_path)  # signed link, not the API key
        with zipfile.ZipFile(zip_path) as z:
            for m in z.namelist():
                if dest.resolve() not in (dest / m).resolve().parents:
                    raise SystemExit(f"unsafe path in archive: {m}")
            z.extractall(dest)
        zip_path.unlink()
    wanted = set(src["classes"])
    return sorted(p for p in dest.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")
                  and p.parent.name in wanted)


def main() -> int:
    downloaded = [(src["project"], p) for src in SOURCES for p in fetch(src)]
    by_source: dict[tuple[str, str], tuple[str, Path]] = {}
    for project, p in downloaded:  # one file per Roboflow source image (augmented copies share the source name)
        by_source.setdefault((project, p.name.split(".rf.")[0]), (project, p))
    items = sorted(by_source.values(), key=lambda t: (t[0], t[1].name))
    hashes = np.stack([dhash_variants(p) for _, p in items])  # (n, 8, 32)
    keep: list[int] = []
    for i in range(len(items)):
        if keep:
            ref = hashes[keep][:, 0]  # (k, 32): kept images, upright
            d = POPCOUNT[np.bitwise_xor(hashes[i][:, None, :], ref[None])].sum(-1).min()
            if d <= ANY_BITS:
                continue
        keep.append(i)
    clean = OUT / "images"
    if clean.exists():
        shutil.rmtree(clean)
    clean.mkdir(parents=True)
    rows = []
    for k, i in enumerate(keep):
        project, p = items[i]
        dst = clean / f"neg{k:04d}{p.suffix.lower()}"
        shutil.copy2(p, dst)
        rows.append(dict(file=dst.name, project=project, source_file=p.name))
    summary = dict(downloaded={s["project"]: sum(pr == s["project"] for pr, _ in downloaded) for s in SOURCES},
                   unique_source_names={s["project"]: sum(pr == s["project"] for pr, _ in items) for s in SOURCES},
                   kept_after_dedup={s["project"]: sum(r["project"] == s["project"] for r in rows) for s in SOURCES},
                   total_downloaded=len(downloaded), total_kept=len(rows), dedup_threshold_bits=ANY_BITS,
                   licence="CC BY 4.0 (both projects, as reported by the Roboflow API)")
    MANIFEST.parent.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(dict(summary=summary, images=rows), indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
