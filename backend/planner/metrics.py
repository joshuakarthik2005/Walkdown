"""Solver-independent plan evaluation and validation.

Both CP-SAT and the priority-sort baseline are scored by ``evaluate`` so the
comparison is like for like, and both are checked by ``validate`` so neither
can win by breaking a constraint.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Assignment, ObjectiveBreakdown, PlannerConfig, Scenario
from .timegrid import end_table, release_hour, shift_hours, window_containing


def moved_jobs(previous: list[Assignment] | None, assignments: list[Assignment], now: int) -> list[str]:
    """Ids of jobs that were planned (not started) before and changed crew or start, or were dropped."""
    if not previous:
        return []
    current = {a.defect_id: a for a in assignments}
    moved = []
    for p in previous:
        if p.start < now:
            continue
        a = current.get(p.defect_id)
        if a is None or a.crew_id != p.crew_id or a.start != p.start:
            moved.append(p.defect_id)
    return sorted(moved)


def evaluate(
    scenario: Scenario,
    config: PlannerConfig,
    assignments: list[Assignment],
    *,
    now: int = 0,
    previous: list[Assignment] | None = None,
) -> ObjectiveBreakdown:
    """Score a plan with the planner objective.

    exposure = sum over defects of risk_weight x (completion hour - found_at),
    where an unscheduled defect counts as unrepaired until the horizon end.
    """
    horizon = scenario.horizon_hours
    done = {a.defect_id: a.end for a in assignments}
    exposure = 0
    critical = 0
    for d in scenario.defects:
        completion = done.get(d.id, horizon)
        exposure += config.risk_weight(d) * (completion - d.found_at)
        if d.id not in done and config.is_critical(d):
            critical += config.critical_penalty
    moves = len(moved_jobs(previous, assignments, now)) * config.move_penalty
    return ObjectiveBreakdown(exposure=exposure, critical_penalty=critical, move_penalty=moves)


def critical_unscheduled(scenario: Scenario, config: PlannerConfig, assignments: list[Assignment]) -> list[str]:
    """Ids of critical defects with no assignment."""
    done = {a.defect_id for a in assignments}
    return sorted(d.id for d in scenario.defects if config.is_critical(d) and d.id not in done)


def crew_utilisation(scenario: Scenario, assignments: list[Assignment], *, now: int = 0) -> dict[str, float]:
    """Share of each crew's available on-shift hours in ``[now, horizon)`` that is booked."""
    horizon = scenario.horizon_hours
    result = {}
    for c in scenario.crews:
        on = shift_hours(c, horizon)
        available = {h for h in range(now, horizon) if on[h] and not any(u.start <= h < u.end for u in c.unavailable)}
        busy = {h for a in assignments if a.crew_id == c.id for h in range(max(a.start, now), a.end) if on[h]}
        result[c.id] = len(busy & available) / len(available) if available else 0.0
    return result


def validate(scenario: Scenario, assignments: list[Assignment], *, now: int = 0,
             fixed_ids: set[str] | None = None) -> list[str]:
    """Return every constraint violation in a plan; an empty list means the plan is valid.

    ``fixed_ids`` are in-progress jobs carried over from a previous plan; they
    are exempt from the release and window checks, which applied when they started.
    """
    fixed_ids = fixed_ids or set()
    errors = []
    seen = set()
    by_crew = defaultdict(list)
    by_permit = defaultdict(list)
    for a in assignments:
        if a.defect_id in seen:
            errors.append(f"{a.defect_id}: assigned twice")
        seen.add(a.defect_id)
        d = scenario.defect(a.defect_id)
        c = scenario.crew(a.crew_id)
        by_crew[c.id].append(a)
        if d.permit:
            by_permit[d.permit].append(a)
        if d.skill not in c.skills:
            errors.append(f"{d.id}: crew {c.id} lacks skill {d.skill}")
        expected_end = end_table(shift_hours(c, scenario.horizon_hours), d.repair_hours).get(a.start)
        if expected_end != a.end:
            errors.append(f"{d.id}: end {a.end} does not match {d.repair_hours} on-shift hours from {a.start}")
        if a.defect_id in fixed_ids:
            continue
        if a.start < release_hour(d, scenario, now):
            errors.append(f"{d.id}: starts at {a.start} before release {release_hour(d, scenario, now)}")
        if d.needs_shutdown and window_containing(scenario, a.start, a.end) is None:
            errors.append(f"{d.id}: shutdown job outside every window")
        if any(u.overlaps(a.start, a.end) for u in c.unavailable):
            errors.append(f"{d.id}: overlaps unavailability of crew {c.id}")
    for crew_id, jobs in by_crew.items():
        jobs.sort(key=lambda a: a.start)
        for x, y in zip(jobs, jobs[1:]):
            if y.start < x.end:
                errors.append(f"crew {crew_id}: {x.defect_id} and {y.defect_id} overlap")
    for permit_id, jobs in by_permit.items():
        cap = scenario.permit(permit_id).max_concurrent
        if cap is None:
            continue
        for h in range(scenario.horizon_hours):
            active = sum(1 for a in jobs if a.start <= h < a.end)
            if active > cap:
                errors.append(f"permit {permit_id}: {active} concurrent jobs at hour {h} (cap {cap})")
                break
    return errors
