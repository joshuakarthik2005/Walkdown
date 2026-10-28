"""Work packages vs one job per defect: exposure, makespan, solver status and setup hours saved.

Both plans are scored on the same per-defect objective (``metrics.evaluate`` on the unpackaged scenario; a
packaged plan is unpacked so every member gets its package's end). The packaged plan is optimal for the
*packaged* problem; the unpackaged plan is the best found within the time limit.

Cases:
- ``devdemo``: the cached 6-photo dev clip (every frame, text + boxes, cached verdicts; no API calls) on the
  12-job demo backlog;
- ``demo-scenario``: the 25-job planner demo scenario, packaged by asset.

    .venv\\Scripts\\python.exe -m benchmark.packages_compare
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.planner.cpsat import solve
from backend.planner.generator import load_scenario
from backend.planner.metrics import evaluate
from backend.planner.models import Defect, Plan, PlannerConfig, Scenario
from backend.planner.packages import PackageConfig, build_packages, setup_hours_saved, unpack

RESULTS = Path(__file__).parent / "results"


def _score(sc: Scenario, cfg: PlannerConfig, plan: Plan, jobs: list[Defect] | None, focus: set[str]) -> dict:
    assignments = unpack(jobs, plan.assignments) if jobs else plan.assignments
    b = evaluate(sc, cfg, assignments, now=plan.now)
    ends = {a.defect_id: a.end for a in assignments}
    severe = {d.id: ends.get(d.id) for d in sc.defects if d.id in focus and d.severity >= 4}
    return dict(status=plan.stats.status, gap=None if plan.stats.gap is None else round(plan.stats.gap, 4),
                solve_s=round(plan.stats.wall_time_s, 2), jobs=len(plan.assignments) + len(plan.unscheduled),
                exposure=b.exposure, unscheduled_penalties=b.critical_penalty + b.high_penalty,
                makespan_h=max((a.end for a in assignments), default=0) - plan.now,
                defects_unscheduled=sorted(d.id for d in sc.defects if d.id not in ends),
                severe_end_hours=severe)


def compare(name: str, base: list[Defect], walk: list[Defect], frames: dict[str, list[int]], sc: Scenario,
            cfg: PlannerConfig, packages: PackageConfig | None = None) -> dict:
    flat = sc.model_copy(update={"defects": base + walk})
    packages = packages or PackageConfig()
    jobs = build_packages(walk, frames, sc.crews, packages, planner=cfg)
    packed = sc.model_copy(update={"defects": base + jobs})
    focus = {d.id for d in walk}
    p0, p1 = solve(flat, cfg), solve(packed, cfg)
    out = dict(case=name, max_package_hours=packages.max_package_hours, defects_packaged=len(walk), packages=sum(1 for j in jobs if j.members),
               jobs_after_packaging=len(jobs), setup_hours_saved=setup_hours_saved(jobs, walk),
               unpackaged=_score(flat, cfg, p0, None, focus), packaged=_score(flat, cfg, p1, jobs, focus))
    s0, s1 = out["unpackaged"]["severe_end_hours"], out["packaged"]["severe_end_hours"]
    out["severe_later_with_packages"] = {k: [s0[k], s1[k]] for k in s0 if (s1[k] or 10**6) > (s0[k] or 10**6)}
    return out


def devdemo_defects() -> tuple[list[Defect], dict[str, list[int]]]:
    from backend.agent.clip import Clip
    from backend.agent.register import to_planner_defect
    from backend.agent.tools import AgentSession, build_register_tool, segment_frames, verify_candidate
    from backend.clients.cost import CostLedger
    s = AgentSession(clip=Clip("devdemo"), ledger=CostLedger(None), verify_effort="minimal")
    segment_frames(s, 0, None, 1.0)
    ids = list(s.candidates)
    for i in range(0, len(ids), 20):
        verify_candidate(s, ids[i:i + 20])
    build_register_tool(s)
    if s.ledger.total() > 0:
        raise RuntimeError("devdemo cache incomplete: this benchmark must not call the APIs")
    return [to_planner_defect(e, found_at=0) for e in s.register], {e.defect_id: e.frames for e in s.register}


def main() -> int:
    from backend.agent.tools import demo_backlog
    cfg = PlannerConfig(time_limit_s=30)
    rows = []
    walk, frames = devdemo_defects()
    backlog, full = demo_backlog(), load_scenario()
    for hours in (8, 16, 24):
        pk = PackageConfig(max_package_hours=hours)
        rows.append(compare("devdemo (41 walkdown defects + 12-job backlog)", backlog.defects, walk, frames, backlog,
                            cfg, pk))
        rows.append(compare("demo scenario (25 jobs, packaged by asset)", [], full.defects, {}, full, cfg, pk))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "packages_compare.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    for r in rows:
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
