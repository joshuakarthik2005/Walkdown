"""F2: Cloud vs On-prem mode, end to end on one clip with every model call live (no perception/verdict cache).

Cloud:   hosted SAM 3.1 (text + Muse Spark box proposals), Muse Spark verifier and agent, Muse Wonder senior review.
On-prem: SAM 3.1 open weights on Modal (one L40S, scale to zero; text prompt + Muse Spark Open box proposals), Muse Spark Open on Baseten
         for verifier and agent. No hosted model is called.

Reports wall time, cost by job, candidates, register entries, walkdown jobs, plan status and gap, and how many
register entries need review. The first On-prem call includes the Modal cold start (container boot and model load).

    .venv\\Scripts\\python.exe -m benchmark.mode_compare devdemo
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from backend.agent.clip import Clip
from backend.agent.loop import WalkdownAgent
from backend.agent.tools import AgentSession
from backend.clients.cost import CostLedger

RESULTS = Path(__file__).parent / "results"
MODES = {"cloud": dict(provider="meta", sam_backend="meta", box_proposals=True),
         "on-prem": dict(provider="baseten", sam_backend="modal", box_proposals=True)}


def run(clip_id: str, mode: str) -> dict:
    clip = Clip(clip_id)
    s = AgentSession(clip=clip, ledger=CostLedger(clip.dir / "cost_ledger.jsonl"), live=True, verify_effort="minimal",
                     **MODES[mode])
    agent = WalkdownAgent(s)
    t0 = time.time()
    agent.run(f"New walkdown clip of {clip.asset.asset_id} is uploaded. Inspect it, build the register, plan the "
              f"repairs and explain the plan.")
    tool_s = {}
    for ev in agent.trace:
        if ev.kind == "tool":
            tool_s[ev.name] = round(tool_s.get(ev.name, 0) + ev.duration_s, 1)
    return dict(mode=mode, wall_s=round(time.time() - t0, 1), tool_seconds=tool_s, usd=round(s.ledger.total(), 4),
                usd_by_job={j: round(s.ledger.total(j), 4) for j in sorted({e.job for e in s.ledger.entries})},
                candidates=len(s.candidates), accepted=sum(1 for v in s.verdicts.values() if not v.grade or v.grade.is_defect),
                register=len(s.register), jobs=len({e.package_id or e.defect_id for e in s.register}),
                needs_review=sum(e.needs_review for e in s.register),
                plan=s.plan.stats.status if s.plan else None,
                gap=None if not s.plan or s.plan.stats.gap is None else round(s.plan.stats.gap, 4),
                agent_turns=sum(1 for ev in agent.trace if ev.kind == "llm"))


def main() -> int:
    clip_id = sys.argv[1] if len(sys.argv) > 1 else "devdemo"
    rows = [run(clip_id, m) for m in MODES]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"mode_compare_{clip_id}.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    for r in rows:
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
