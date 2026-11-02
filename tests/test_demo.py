"""Public demo mode: spend cap, rate limits, upload limits, samples forced to cached results, examples, bundled clips."""

import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.agent import clip as clip_mod
from backend.api import app as app_mod
from backend.api.demo import BUDGET_MESSAGE, BudgetExceeded, DemoConfig, GuardedLedger, RateLimiter, SpendGuard
from backend.clients.cost import CostEntry

client = TestClient(app_mod.app)


def entry(usd):
    return CostEntry(job="t", model="m", usd=usd)


def test_spend_guard_caps_persists_and_rolls_over(tmp_path):
    now = [1_800_000_000.0]
    g = SpendGuard(1.0, tmp_path, clock=lambda: now[0])
    g.add(0.6)
    g.check()  # still under the cap
    g.add(0.5)
    assert g.exhausted() and g.remaining() == 0
    with pytest.raises(Exception) as err:
        g.check()
    assert err.value.status_code == 429 and err.value.detail == BUDGET_MESSAGE
    assert SpendGuard(1.0, tmp_path, clock=lambda: now[0]).exhausted()  # a restart keeps the day's spend
    now[0] += 86_400  # next UTC day
    assert not g.exhausted() and g.spent() == 0


def test_guarded_ledger_stops_a_run_at_the_cap(tmp_path):
    g = SpendGuard(0.05, None)
    ledger = GuardedLedger(None, g)
    ledger.add(entry(0.03))
    with pytest.raises(BudgetExceeded):
        ledger.add(entry(0.03))
    assert ledger.total() == pytest.approx(0.06)  # the paid call is still recorded


def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter(dict(run=2), window_s=60, clock=lambda: now[0])
    rl.hit("1.2.3.4", "run")
    rl.hit("1.2.3.4", "run")
    with pytest.raises(Exception) as err:
        rl.hit("1.2.3.4", "run")
    assert err.value.status_code == 429
    rl.hit("5.6.7.8", "run")  # other clients are not affected
    rl.hit("1.2.3.4", "unlimited-action")
    now[0] = 61
    rl.hit("1.2.3.4", "run")


def test_demo_config_from_env(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_DAILY_CAP_USD", "2.5")
    monkeypatch.setenv("CORS_ORIGINS", "https://walkdown.vercel.app, https://x.example")
    monkeypatch.setenv("DEMO_LIMIT_ASK_PER_HOUR", "3")
    c = DemoConfig.from_env()
    assert c.enabled and c.daily_cap_usd == 2.5 and c.limits["ask"] == 3
    assert c.cors_origins == ["https://walkdown.vercel.app", "https://x.example"]
    monkeypatch.delenv("DEMO_MODE")
    assert DemoConfig.from_env().enabled is False


@pytest.fixture
def demo(monkeypatch, tmp_path):
    """Demo mode on, a fresh budget and rate limiter, and a fake agent (no API calls)."""
    cfg = DemoConfig(enabled=True, daily_cap_usd=1.0, max_upload_mb=1, max_duration_s=5.0)
    guard = SpendGuard(1.0, tmp_path)
    monkeypatch.setattr(app_mod, "DEMO", cfg)
    monkeypatch.setattr(app_mod, "GUARD", guard)
    monkeypatch.setattr(app_mod, "LIMITER", RateLimiter(cfg.limits))
    monkeypatch.setattr(app_mod, "MAX_UPLOAD_MB", 1)
    seen = {}

    class FakeAgent:
        def __init__(self, session, reasoning_effort="low"):
            self.s, self.trace = session, []
            seen["session"] = session

        def run(self, message):
            return "ok"

    class FakeClip:
        def __init__(self, clip_id):
            self.clip_id, self.dir = clip_id, tmp_path / clip_id
            self.asset = SimpleNamespace(asset_id="PIPE-1", location="")

    monkeypatch.setattr(app_mod, "WalkdownAgent", FakeAgent)
    monkeypatch.setattr(app_mod, "Clip", FakeClip)
    return SimpleNamespace(guard=guard, seen=seen, cfg=cfg)


def test_demo_samples_use_cached_results_and_onprem_is_examples_only(demo):
    r = client.post("/runs", json={"clip_id": "stock-tank-farm", "live": True})
    assert r.status_code == 200 and demo.seen["session"].live is False  # live forced off on a sample
    assert isinstance(demo.seen["session"].ledger, GuardedLedger)  # agent turns count toward the cap
    r = client.post("/runs", json={"clip_id": "clip-abc", "live": True})
    assert r.status_code == 200 and demo.seen["session"].live is True  # uploads have no cache to fall back on
    r = client.post("/runs", json={"clip_id": "stock-tank-farm", "provider": "baseten"})
    assert r.status_code == 403 and "finished example" in r.json()["detail"]


def test_demo_budget_blocks_paid_endpoints(demo):
    demo.guard.add(1.0)
    r = client.post("/runs", json={"clip_id": "stock-tank-farm"})
    assert r.status_code == 429 and r.json()["detail"] == BUDGET_MESSAGE
    assert client.get("/config").json()["budget_available"] is False
    up = client.post("/clips", data={"asset_id": "PIPE-1"}, files=[("files", ("a.jpg", b"x", "image/jpeg"))])
    assert up.status_code == 429


def test_demo_rate_limit_on_runs(demo):
    demo.cfg.limits["run"] = 2
    codes = [client.post("/runs", json={"clip_id": "stock-tank-farm"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_demo_upload_limits(demo, monkeypatch, tmp_path):
    big = client.post("/clips", data={"asset_id": "PIPE-1"},
                      files=[("files", ("a.jpg", b"x" * ((1 << 20) + 10), "image/jpeg"))])
    assert big.status_code == 413 and "1 MB" in big.json()["detail"]
    created = {}

    def fake_create(clip_id, video=None, photos=None, asset=None):
        d = tmp_path / clip_id
        d.mkdir()
        created["dir"] = d
        return SimpleNamespace(dir=d, duration_s=9.0)

    monkeypatch.setattr(app_mod, "create_clip", fake_create)
    long = client.post("/clips", data={"asset_id": "PIPE-1"}, files=[("files", ("a.mp4", b"x", "video/mp4"))])
    assert long.status_code == 400 and "too long" in long.json()["detail"]
    assert not created["dir"].exists()  # the rejected clip is removed


def make_bundled_clip(root, clip_id="bundle", duration=2.0, fps=2.0):
    d = root / clip_id
    (d / "frames").mkdir(parents=True)
    for t in np.arange(0, duration + 1e-9, 1 / fps):
        cv2.imwrite(str(d / "frames" / f"t{int(round(t * 10)):05d}.jpg"), np.full((40, 60, 3), 128, np.uint8))
    (d / "clip.json").write_text(json.dumps(dict(asset=dict(asset_id="B-1"), video=dict(duration_s=duration))))
    return d


def test_bundled_clip_without_source_video(monkeypatch, tmp_path):
    monkeypatch.setattr(clip_mod, "CLIPS_DIR", tmp_path)
    make_bundled_clip(tmp_path)
    c = clip_mod.Clip("bundle")
    assert c.source is None and c.bundled and c.is_video and c.duration_s == 2.0
    frames = c.frames(0.0, None, 2.0)
    assert [f.index for f in frames] == [0, 5, 10, 15, 20] and all(f.path.exists() for f in frames)


def test_example_round_trip_rebases_paths(monkeypatch, tmp_path):
    from backend.agent.loop import TraceEvent, WalkdownAgent
    from backend.agent.tools import AgentSession
    from backend.api import examples
    from backend.clients.cost import CostLedger

    monkeypatch.setattr(clip_mod, "CLIPS_DIR", tmp_path / "a")
    make_bundled_clip(tmp_path / "a")
    s = AgentSession(clip=clip_mod.Clip("bundle"), ledger=CostLedger(None))
    s.frame_paths = {5: tmp_path / "a" / "bundle" / "frames" / "t00005.jpg"}
    s.voice_notes.append(dict(transcript="hello"))
    agent = WalkdownAgent(s)
    agent.trace.append(TraceEvent(step=1, kind="final", name="final answer", summary="done", started_at=0.0, duration_s=0.1))
    examples.save_run(tmp_path / "ex.pkl.gz", agent, ["answer"], dict(id="ex"))
    # the data folder moves (another machine): paths follow the clip
    monkeypatch.setattr(clip_mod, "CLIPS_DIR", tmp_path / "b")
    make_bundled_clip(tmp_path / "b")
    loaded, answers, meta = examples.load_run(tmp_path / "ex.pkl.gz")
    assert answers == ["answer"] and meta["id"] == "ex" and loaded.trace[0].summary == "done"
    assert loaded.s.frame_paths[5] == tmp_path / "b" / "bundle" / "frames" / "t00005.jpg"
    assert loaded.s.voice_notes == [dict(transcript="hello")] and loaded.s.clip.dir == tmp_path / "b" / "bundle"
