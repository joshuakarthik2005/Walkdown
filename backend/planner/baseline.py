"""Priority-sort baseline: greedy earliest-finish scheduling by severity.

Defects are taken in order of severity, then failure risk (both descending),
and each is placed on the eligible crew where it can finish earliest, without
overlapping that crew's booked work or exceeding a permit's concurrency cap.
This is the "sort by severity and fill the calendar" practice that CP-SAT is
compared against. It honours exactly the same constraints.
"""

from __future__ import annotations

import time

from .common import build_plan, fixed_jobs
from .models import Assignment, Plan, PlannerConfig, Scenario, SolveStats
from .timegrid import feasible_slots, release_hour


def priority_sort(
    scenario: Scenario,
    config: PlannerConfig | None = None,
    *,
    now: int = 0,
    previous: Plan | None = None,
) -> Plan:
    """Schedule greedily by priority and return a plan scored by the shared objective."""
    config = config or PlannerConfig()
    t0 = time.perf_counter()
    horizon = scenario.horizon_hours

    fixed = fixed_jobs(scenario, previous, now)
    fixed_ids = {a.defect_id for a in fixed}
    crew_busy = {c.id: [False] * horizon for c in scenario.crews}
    permit_load = {p.id: [0] * horizon for p in scenario.permits}

    def book(a: Assignment) -> None:
        permit = scenario.defect(a.defect_id).permit
        for h in range(a.start, min(a.end, horizon)):
            crew_busy[a.crew_id][h] = True
            if permit:
                permit_load[permit][h] += 1

    for a in fixed:
        book(a)

    queue = sorted((d for d in scenario.defects if d.id not in fixed_ids),
                   key=lambda d: (-d.severity, -d.failure_risk, d.repair_hours, d.id))
    assignments = list(fixed)
    for d in queue:
        permit = scenario.permit(d.permit)
        cap = permit.max_concurrent if permit else None
        release = release_hour(d, scenario, now)
        best: Assignment | None = None
        for c in scenario.crews:
            for s, e in sorted(feasible_slots(d, c, scenario, release).items()):
                if any(crew_busy[c.id][s:e]):
                    continue
                if cap is not None and any(load >= cap for load in permit_load[d.permit][s:e]):
                    continue
                if best is None or (e, c.id) < (best.end, best.crew_id):
                    best = Assignment(defect_id=d.id, crew_id=c.id, start=s, end=e)
                break  # ends grow with starts, so the first free slot finishes earliest on this crew
        if best is not None:
            book(best)
            assignments.append(best)
    assignments.sort(key=lambda a: (a.start, a.crew_id))

    stats = SolveStats(solver="priority-sort", status="HEURISTIC", wall_time_s=time.perf_counter() - t0)
    plan = build_plan(scenario, config, assignments, stats, now=now, previous=previous, fixed_ids=fixed_ids)
    plan.stats.objective = float(plan.breakdown.total)
    return plan
