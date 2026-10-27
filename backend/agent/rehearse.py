"""Rehearse the 3-minute demo flow through the HTTP API, timing each stage.

Runs exactly what the UI does: start a run on a (cached) clip, poll the
trace until done, fetch register/plan/frames, post a constraint change
(default: cancel the first shutdown window, epsilon 0.02), poll until done.
Prints wall time per stage, cost, plan status/gap, register size and the
agent's two answers, so the video can be planned against real timings.

    .venv\\Scripts\\python.exe -m backend.agent.rehearse <clip_id> [--change crew|window]
"""

from __future__ import annotations

import argparse
import sys
import time

from fastapi.testclient import TestClient

from backend.api.app import app


def wait(client: TestClient, run_id: str) -> dict:
    while True:
        st = client.get(f"/runs/{run_id}").json()
        if st["status"] != "running":
            return st
        time.sleep(1)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_id")
    ap.add_argument("--change", choices=["crew", "window"], default="window")
    ap.add_argument("--now", type=int, default=24)
    args = ap.parse_args()
    c = TestClient(app)
    t0 = time.time()
    run_id = c.post("/runs", json={"clip_id": args.clip_id}).json()["run_id"]
    st = wait(c, run_id)
    t_run = time.time() - t0
    reg = c.get(f"/runs/{run_id}/register").json()
    plan = c.get(f"/runs/{run_id}/plan").json()
    frames = c.get(f"/runs/{run_id}/frames").json()["frames"]
    stats = plan["plan"]["stats"]
    print(f"run:    {t_run:5.1f} s  ${st['usd']:.4f}  register {len(reg['entries'])}  frames {len(frames)}  "
          f"plan {stats['status']} gap {100 * (stats['gap'] or 0):.1f}%  status {st['status']} {st['error'] or ''}")
    if args.change == "window":
        change = {"type": "shutdown_window_changed", "window_id": plan["scenario"]["windows"][0]["id"]}
    else:
        busiest = max(plan["scenario"]["crews"], key=lambda cr: sum(
            a["end"] - a["start"] for a in plan["plan"]["assignments"] if a["crew_id"] == cr["id"]))["id"]
        change = {"type": "crew_unavailable", "crew_id": busiest, "start": args.now, "end": args.now + 72}
    t1 = time.time()
    c.post(f"/runs/{run_id}/changes", json={"change": change, "now_hour": args.now, "epsilon": 0.02})
    st = wait(c, run_id)
    plan = c.get(f"/runs/{run_id}/plan").json()
    stats = plan["plan"]["stats"]
    print(f"change: {time.time() - t1:5.1f} s  total ${st['usd']:.4f}  {change}  plan {stats['status']} "
          f"gap {100 * (stats['gap'] or 0):.1f}%  moved {len(plan['plan']['moved_jobs'])}")
    for i, a in enumerate(st["answers"]):
        print(f"\n--- answer {i + 1} ({len(a.split())} words) ---\n{a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
