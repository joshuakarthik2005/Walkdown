"""Planner gap on the demo case: cached devdemo register + plant backlog, at the demo time limit.

Uses only cached perception/verification (no API calls). Reports status, gap
and solve time for several backlog sizes and solver settings.

    .venv\\Scripts\\python.exe -m benchmark.demo_gap
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from backend.agent.clip import Clip
from backend.agent.register import to_planner_defect
from backend.agent.tools import AgentSession, build_register_tool, segment_frames, verify_candidate
from backend.clients.cost import CostLedger
from backend.planner.cpsat import solve
from backend.planner.generator import load_scenario
from backend.planner.models import PlannerConfig

OUT = Path(__file__).parent / "results" / "demo_gap.json"


def walkdown_defects(effort: str = "minimal"):
    s = AgentSession(clip=Clip("devdemo"), ledger=CostLedger(), verify_effort=effort)
    segment_frames(s, fps=0.75)
    verify_candidate(s, list(s.candidates))
    if s.ledger.total() > 0:
        raise SystemExit("cache miss: this script must not call the API")
    build_register_tool(s)
    return [to_planner_defect(e, found_at=0) for e in s.register]


def main(configs: list[tuple[str, int, PlannerConfig]]) -> int:
    walk = walkdown_defects()
    base = load_scenario()
    rows = []
    for label, n_backlog, cfg in configs:
        sc = base.model_copy(update={"defects": base.defects[:n_backlog] + walk})
        p = solve(sc, cfg)
        rows.append(dict(label=label, backlog=n_backlog, walkdown=len(walk), defects=len(sc.defects),
                         status=p.stats.status, gap=p.stats.gap, wall_s=p.stats.wall_time_s,
                         objective=p.stats.objective, unscheduled=len(p.unscheduled)))
        print(f"{label:34} defects {len(sc.defects):3}  {p.stats.status:8} gap {100 * (p.stats.gap or 0):5.1f}% "
              f"{p.stats.wall_time_s:5.1f}s  unscheduled {len(p.unscheduled)}", flush=True)
    OUT.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    cores = os.cpu_count() or 8
    before = PlannerConfig(num_workers=4, time_limit_s=30)
    after = PlannerConfig(num_workers=cores, time_limit_s=30)
    sys.exit(main([
        ("before: 4 workers, full backlog", 25, before),
        (f"{cores} workers, full backlog", 25, after),
        (f"{cores} workers, backlog 15", 15, after),
        (f"{cores} workers, backlog 10", 10, after),
    ]))
