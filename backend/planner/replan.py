"""Replanning: apply a constraint change at time ``now`` and re-solve.

Work that started before ``now`` is fixed (it finishes as planned, on the
same crew). Every other previously planned job may move, but each move costs
``PlannerConfig.move_penalty``, so the new plan stays close to the old one
unless moving clearly reduces risk. The returned plan lists the moved jobs.
"""

from __future__ import annotations

from pydantic import BaseModel

from .cpsat import solve
from .models import Change, CrewUnavailable, NewDefect, Plan, PlannerConfig, Scenario, ShutdownWindow, \
    ShutdownWindowChanged, TimeRange


class ReplanResult(BaseModel):
    """The changed scenario, the new plan and a compact diff against the old plan."""

    change: Change
    scenario: Scenario
    plan: Plan
    moved_jobs: list[str]
    newly_scheduled: list[str]
    newly_unscheduled: list[str]
    objective_before: int
    objective_after: int


def apply_change(scenario: Scenario, change: Change, now: int) -> Scenario:
    """Return a copy of the scenario with the change applied."""
    sc = scenario.model_copy(deep=True)
    if isinstance(change, CrewUnavailable):
        crew = sc.crew(change.crew_id)  # raises StopIteration for an unknown crew
        crew.unavailable.append(TimeRange(start=change.start, end=change.end))
    elif isinstance(change, ShutdownWindowChanged):
        if not any(w.id == change.window_id for w in sc.windows):
            raise ValueError(f"unknown shutdown window {change.window_id!r}")
        sc.windows = [w for w in sc.windows if w.id != change.window_id]
        if change.new_start is not None and change.new_end is not None:
            sc.windows.append(ShutdownWindow(id=change.window_id, start=change.new_start, end=change.new_end))
            sc.windows.sort(key=lambda w: w.start)
        elif (change.new_start is None) != (change.new_end is None):
            raise ValueError("give both new_start and new_end, or neither to cancel the window")
    elif isinstance(change, NewDefect):
        if any(d.id == change.defect.id for d in sc.defects):
            raise ValueError(f"defect {change.defect.id!r} already exists")
        defect = change.defect.model_copy(update={"found_at": max(change.defect.found_at, now)})
        sc.defects.append(defect)
    # Re-validate the whole scenario (unknown permits, duplicate ids, ...).
    return Scenario.model_validate(sc.model_dump())


def replan(
    scenario: Scenario,
    previous: Plan,
    change: Change,
    *,
    now: int,
    config: PlannerConfig | None = None,
) -> ReplanResult:
    """Apply ``change`` at hour ``now`` and re-solve, keeping started work fixed."""
    if now < previous.now:
        raise ValueError(f"cannot replan at hour {now}, before the previous plan's hour {previous.now}")
    config = config or PlannerConfig()
    changed = apply_change(scenario, change, now)
    plan = solve(changed, config, now=now, previous=previous)
    before = {a.defect_id for a in previous.assignments}
    after = {a.defect_id for a in plan.assignments}
    return ReplanResult(
        change=change,
        scenario=changed,
        plan=plan,
        moved_jobs=plan.moved_jobs,
        newly_scheduled=sorted(after - before),
        newly_unscheduled=sorted(before - after),
        objective_before=previous.breakdown.total,
        objective_after=plan.breakdown.total,
    )
