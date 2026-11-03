"""Demo data bundle (backend/api/bundle.py) and bit-packed instance masks (backend/perception/sam.py)."""

import pickle
import tarfile

import numpy as np
import pytest

from backend.api import bundle
from backend.perception.sam import Instance


def _fake_data(root):
    for c in bundle.SAMPLES:
        d = root / "clips" / c
        (d / "frames").mkdir(parents=True)
        (d / "frames" / "t00000.jpg").write_bytes(b"jpg")
        (d / "clip.json").write_text("{}")
        (d / "source.mp4").write_bytes(b"stock video")
        (d / "cost_ledger.jsonl").write_text("{}")
    (root / "examples").mkdir()
    (root / "examples" / "tank-farm.pkl.gz").write_bytes(b"x")
    (root / "runs" / "decoded_masks" / "ab").mkdir(parents=True)
    (root / "runs" / "decoded_masks" / "ab" / "k.json").write_text("[]")
    (root / "runs" / "other.log").write_text("not bundled")


def test_pack_excludes_videos_and_ledgers_and_fetch_unpacks(tmp_path, monkeypatch):
    src, dest = tmp_path / "src", tmp_path / "out"
    _fake_data(src)
    tar_path = tmp_path / "b.tar.gz"
    n = bundle.pack(tar_path, src)
    names = tarfile.open(tar_path).getnames()
    assert n == len(names) == 3 * 2 + 2
    assert not any(x.endswith((".mp4", "cost_ledger.jsonl", "other.log")) for x in names)

    monkeypatch.setenv("DEMO_BUNDLE_PATH", str(tar_path))
    assert bundle.fetch(dest)
    assert (dest / "clips" / "stock-tank-farm" / "frames" / "t00000.jpg").read_bytes() == b"jpg"
    assert (dest / bundle.MARKER).exists()
    assert tar_path.exists()  # a local tarball is left in place
    assert bundle.fetch(dest)  # already unpacked: no-op


def test_fetch_without_token_starts_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("DEMO_BUNDLE_PATH", raising=False)
    assert bundle.fetch(tmp_path) is False


def test_pack_requires_every_sample(tmp_path):
    with pytest.raises(FileNotFoundError):
        bundle.pack(tmp_path / "b.tar.gz", tmp_path)


def test_instance_mask_is_packed_and_round_trips():
    rng = np.random.default_rng(0)
    m = rng.random((720, 1280)) > 0.7
    inst = Instance("0", (0, 0, 1280, 720), m, 0.9)
    assert np.array_equal(inst.mask, m) and inst.area == int(m.sum())
    assert inst._bits.nbytes == m.size // 8
    with pytest.raises(ValueError):
        inst.mask[0, 0] = True  # read-only: writes would be lost
    again = pickle.loads(pickle.dumps(inst))
    assert np.array_equal(again.mask, m)


def test_instance_loads_pickles_with_unpacked_masks():
    m = np.zeros((4, 6), bool)
    m[1:3, 2:5] = True
    old = Instance.__new__(Instance)
    old.__setstate__(dict(object_id="1", box=(2, 1, 5, 3), mask=m, confidence=None, frame=3))
    assert np.array_equal(old.mask, m) and old.area == 6 and old.frame == 3
