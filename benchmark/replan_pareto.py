r"""Stability vs risk: Pareto points of the two-stage replan on the demo scenario.

For each epsilon, the same changes are applied at hour 48 to the same CP-SAT
plan; reports jobs moved, hours displaced and risk-weighted exposure.

    .venv\Scripts\python.exe -m benchmark.replan_pareto
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.planner.cpsat import solve
from backend.planner.generator import load_scenario
from backend.planner.models import CrewUnavailable, PlannerConfig, ShutdownWindowChanged
from backend.planner.replan import replan

EPSILONS = (0.0, 0.02, 0.05, 0.10)
NOW = 48
OUT = Path(__file__).parent / "results" / "replan_pareto_demo.json"


def main() -> int:
    config = PlannerConfig(num_workers=4)
    sc = load_scenario()
    base = solve(sc, config)
    hours = {c.id: sum(a.end - a.start for a in base.assignments if a.crew_id == c.id) for c in sc.crews}
    busiest = max(sorted(hours), key=hours.get)
    changes = {"crew_unavailable": CrewUnavailable(crew_id=busiest, start=NOW, end=NOW + 72),
               "window_cancelled": ShutdownWindowChanged(window_id=sc.windows[0].id)}
    rows = []
    for name, change in changes.items():
        for eps in EPSILONS:
            r = replan(sc, base, change, now=NOW, config=config, epsilon=eps)
            prev = {a.defect_id: a for a in base.assignments if a.start >= NOW}
            new = {a.defect_id: a for a in r.plan.assignments}
            displaced = sum(abs(new[d].start - p.start) if d in new else sc.horizon_hours - p.start
                            for d, p in prev.items())
            rows.append(dict(change=name, epsilon=eps, moved=len(r.moved_jobs), displaced_hours=displaced,
                             exposure=r.plan.breakdown.exposure,
                             risk=r.plan.breakdown.total - r.plan.breakdown.move_penalty,
                             unscheduled=len(r.plan.unscheduled), status=r.plan.stats.status,
                             stages=[s["status"] for s in r.plan.stats.stages]))
            print(f"{name:17} eps {eps:.2f}: moved {rows[-1]['moved']:2} displaced {displaced:4} h "
                  f"exposure {rows[-1]['exposure']:>8} {rows[-1]['status']}", flush=True)
    OUT.write_text(json.dumps(dict(scenario="demo", now=NOW, busiest_crew=busiest, rows=rows), indent=1) + "\n",
                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
