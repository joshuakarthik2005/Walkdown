import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api import app as app_mod

client = TestClient(app_mod.app)


def test_health_and_unknown_ids():
    assert client.get("/health").json()["ok"] is True
    assert client.post("/runs", json={"clip_id": "does-not-exist"}).status_code == 404
    assert client.get("/runs/run-nope").status_code == 404
    assert client.get("/runs/run-nope/trace").status_code == 404


def test_upload_rejects_bad_input():
    bad_type = client.post("/clips", data={"asset_id": "PIPE-1"}, files=[("files", ("a.txt", b"x", "text/plain"))])
    assert bad_type.status_code == 400
    bad_asset = client.post("/clips", data={"asset_id": "../etc"}, files=[("files", ("a.jpg", b"x", "image/jpeg"))])
    assert bad_asset.status_code == 400


def test_run_lifecycle_with_fake_agent(monkeypatch):
    class FakeAgent:
        def __init__(self, session, reasoning_effort="low"):
            self.s = session
            self.trace = []

        def run(self, message):
            time.sleep(0.05)
            return f"ok: {message[:20]}"

    class FakeClip:
        def __init__(self, clip_id):
            self.clip_id, self.dir = clip_id, app_mod.CLIPS_DIR / "unused"
            self.asset = SimpleNamespace(asset_id="PIPE-1", location="")

    monkeypatch.setattr(app_mod, "WalkdownAgent", FakeAgent)
    monkeypatch.setattr(app_mod, "Clip", FakeClip)
    monkeypatch.setattr(app_mod, "CostLedger", lambda path: SimpleNamespace(total=lambda: 0.0))
    run_id = client.post("/runs", json={"clip_id": "x"}).json()["run_id"]
    for _ in range(100):
        st = client.get(f"/runs/{run_id}").json()
        if st["status"] != "running":
            break
        time.sleep(0.02)
    assert st["status"] == "done" and st["answers"][0].startswith("ok: New walkdown clip")
    assert client.get(f"/runs/{run_id}/plan").status_code == 409  # no plan yet
    change = {"change": {"type": "crew_unavailable", "crew_id": "C1", "start": 0, "end": 10}, "now_hour": 0}
    assert client.post(f"/runs/{run_id}/changes", json=change).status_code == 409


def test_sensitivity_options_are_measured_operating_points():
    r = client.get("/sensitivity").json()
    assert r["default"] == "high_recall"
    hr, bal = r["options"]["high_recall"], r["options"]["balanced"]
    assert hr["recall"]["value"] > bal["recall"]["value"] and hr["false_alarm_images"]["value"] > bal["false_alarm_images"]["value"]
    for o in r["options"].values():
        assert o["recall"]["n"] == 113 and o["false_alarm_images"]["n"] == 191 and len(o["recall"]["ci"]) == 2
