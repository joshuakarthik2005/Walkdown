"""Warm the perception/verification caches for a demo clip by running the agent on it.

The agent chooses its own sampling rates, so the clip is run twice: the
first run fills the caches, the second shows how much of a repeat run is
served from cache (it should cost only the Muse Spark agent turns). Prints
the register size, plan status and cost of each run.

    .venv\\Scripts\\python.exe -m backend.agent.warm_cache <clip_id> [--effort minimal] [--provider baseten]
"""

from __future__ import annotations

import argparse
import sys
import time

from backend.agent.clip import Clip
from backend.agent.loop import WalkdownAgent
from backend.agent.tools import AgentSession
from backend.clients.cost import CostLedger

DEMO_MAX_JOBS = 6  # walkdown jobs (work packages); with the 12-job demo backlog plans stay provably optimal


def run_once(clip_id: str, effort: str, provider: str = "meta") -> dict:
    clip = Clip(clip_id)
    session = AgentSession(clip=clip, ledger=CostLedger(clip.dir / "cost_ledger.jsonl"), verify_effort=effort,
                           provider=provider, sam_backend="modal" if provider == "baseten" else "meta")  # On-prem: open weights only
    agent = WalkdownAgent(session)
    t0 = time.time()
    agent.run(f"New walkdown clip of {clip.asset.asset_id} is uploaded. Inspect it, build the register, plan the "
              f"repairs and explain the plan.")
    by_job = {j: round(session.ledger.total(j), 4) for j in sorted({e.job for e in session.ledger.entries})}
    return dict(seconds=round(time.time() - t0, 1), usd=round(session.ledger.total(), 4), by_job=by_job,
                register=len(session.register), jobs=len({e.package_id or e.defect_id for e in session.register}),
                plan=session.plan.stats.status if session.plan else None,
                gap=session.plan.stats.gap if session.plan else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_id")
    ap.add_argument("--effort", default="minimal")
    ap.add_argument("--provider", choices=["meta", "baseten"], default="meta")
    args = ap.parse_args()
    for label in ("fill", "repeat"):
        r = run_once(args.clip_id, args.effort, args.provider)
        print(f"{label:6} {r}", flush=True)
    if r["jobs"] > DEMO_MAX_JOBS:
        print(f"note: {r['jobs']} walkdown jobs > {DEMO_MAX_JOBS}; the plan may end FEASIBLE with a gap "
              f"within the 30 s limit. Consider a shorter or cleaner clip for the video.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
