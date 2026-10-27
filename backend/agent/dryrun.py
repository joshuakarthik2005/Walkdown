"""Agent dry run: a short photo "clip" from the dev split, the planner demo backlog, one replan.

Internal only: dev images are dataset images and are never shown publicly
(DECISIONS.md). The clip, caches and the trace stay on WALKDOWN_DATA_DIR.

    .venv\\Scripts\\python.exe -m backend.agent.dryrun [--live]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from backend.agent.clip import CLIPS_DIR, Clip, create_clip
from backend.agent.loop import WalkdownAgent
from backend.agent.tools import AgentSession
from backend.clients.cost import CostLedger
from benchmark.download_dataset import RAW_DIR
from benchmark.splits import load_split

CLIP_ID = "devdemo"
N_FRAMES = 6


def main(live: bool = False) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not (CLIPS_DIR / CLIP_ID).exists():
        photos = [RAW_DIR / rel for rel in load_split("dev")[:N_FRAMES]]
        create_clip(CLIP_ID, photos=photos, asset={"asset_id": "PIPE-RACK-207", "asset_type": "pipe",
                                                   "pressurised": True, "location": "unit 2 east rack"})
    ledger = CostLedger(CLIPS_DIR / CLIP_ID / "cost_ledger.jsonl")
    session = AgentSession(clip=Clip(CLIP_ID), ledger=ledger, live=live)
    agent = WalkdownAgent(session, on_event=lambda e: print(f"[{e.step:2}] {e.kind:5} {e.name:18} "
                                                             f"{e.duration_s:5.1f}s ${e.usd:.4f}  {e.summary}"[:160],
                                                             flush=True))
    t0 = time.time()
    answer1 = agent.run("New walkdown clip of PIPE-RACK-207 (unit 2 east rack) is uploaded. Inspect it, "
                        "build the register, plan the repairs and explain the plan.")
    cost1, wall1 = ledger.total(), time.time() - t0
    crew = session.plan.assignments[0].crew_id if session.plan and session.plan.assignments else "C1"
    answer2 = agent.run(f"Update: crew {crew} is unavailable from hour 48 to hour 120. It is now hour 48. "
                        "Replan and tell me what changed.")
    out = dict(live=live, answer_initial=answer1, answer_replan=answer2,
               cost=dict(initial_run_usd=cost1, total_usd=ledger.total(), by_job={
                   j: ledger.summary(j) for j in sorted({e.job for e in ledger.entries})}),
               wall_s=dict(initial=wall1, total=time.time() - t0),
               trace=[e.model_dump(mode="json", exclude={"result"}) for e in agent.trace])
    path = CLIPS_DIR / CLIP_ID / f"dryrun_{'live' if live else 'cached'}_{int(time.time())}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\n=== ANSWER 1 ===\n" + answer1 + "\n\n=== ANSWER 2 ===\n" + answer2)
    print(f"\ncost: initial ${cost1:.4f}, total ${ledger.total():.4f}; wall {out['wall_s']}; trace -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(live="--live" in sys.argv))
