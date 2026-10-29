"""F3 video tracking: best frame per track, one candidate per track, register frames span the track."""

from types import SimpleNamespace

import numpy as np

from backend.agent import tools
from backend.agent.register import AssetInfo
from backend.clients.cost import CostLedger
from backend.perception.sam import Instance, SegmentationResult


def inst(obj, frame, size, conf=0.9):
    m = np.zeros((40, 40), bool)
    m[:size, :size] = True
    return Instance(object_id=obj, box=(0, 0, size, size), mask=m, confidence=conf, frame=frame)


def test_best_frame_is_largest_confident_view():
    best = tools.best_track_frames([inst("1", 0, 5), inst("1", 1, 12), inst("1", 2, 12, 0.5), inst("2", 3, 4)])
    assert best["1"][0].frame == 1 and best["1"][1] == [0, 1, 2]
    assert best["2"][0].frame == 3 and best["2"][1] == [3]


def test_track_video_makes_one_candidate_per_track(tmp_path, monkeypatch):
    frames = [SimpleNamespace(index=i * 5, time_s=i * 0.5, path=tmp_path / f"t{i}.jpg",
                              image=lambda: np.zeros((40, 40, 3), np.uint8)) for i in range(4)]
    clip = SimpleNamespace(source=tmp_path / "source.mp4", dir=tmp_path, frames=lambda a, b, fps: frames,
                           asset=AssetInfo(asset_id="P-1"))
    found = [inst("7", 0, 6), inst("7", 2, 14), inst("9", 3, 8)]
    monkeypatch.setattr(tools, "segment_video", lambda *a, **k: SegmentationResult("rust", 40, 40, found, 0.01, "raw"))
    s = tools.AgentSession(clip=clip, ledger=CostLedger(), base_scenario=tools.demo_backlog(1))
    out = tools.track_video(s, fps=2)
    assert out["tracks"] == 2 and {c["id"] for c in out["candidates"]} == {"T7", "T9"}
    assert s.candidates["T7"][0] == 10 and s.tracks["T7"] == [0, 10]  # best frame index (frame 2 -> index 10)
    assert (tmp_path / "sam_video" / "rust_2fps.txt").read_text() == "raw"
    assert tools.track_video(SimpleNamespace(clip=SimpleNamespace(source=None)))["error"]


def test_frame_reference_from_the_parser_is_read_as_an_int():
    import meta_sam_parser as msp
    from backend.perception.sam import _frame_index
    assert _frame_index(msp.FrameReference(frame_index=7)) == 7 and _frame_index(None) == 0 and _frame_index(3) == 3
