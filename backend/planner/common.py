"""Helpers shared by the CP-SAT solver and the priority-sort baseline."""

from __future__ import annotations

from .explain import explain
from .metrics import critical_unscheduled, evaluate, moved_jobs
from .models import Assignment, Plan, PlannerConfig, Scenario, SolveStats


def fixed_jobs(scenario: Scenario, previous: Plan | None, now: int) -> list[Assignment]:
    """Jobs from the previous plan that started before ``now`` and so cannot change."""
    if previous is None:
        return []
    ids = {d.id for d in scenario.defects}
    return [a for a in previous.assignments if a.start < now and a.defect_id in ids]


def build_plan(
    scenario: Scenario,
    config: PlannerConfig,
    assignments: list[Assignment],
    stats: SolveStats,
    *,
    now: int,
    previous: Plan | None,
    fixed_ids: set[str],
) -> Plan:
    """Assemble a Plan with the shared objective breakdown and explanations."""
    prev_assignments = previous.assignments if previous else None
    done = {a.defect_id for a in assignments}
    plan = Plan(
        scenario_name=scenario.name,
        now=now,
        assignments=sorted(assignments, key=lambda a: (a.start, a.crew_id)),
        unscheduled=sorted(d.id for d in scenario.defects if d.id not in done),
        stats=stats,
        breakdown=evaluate(scenario, config, assignments, now=now, previous=prev_assignments),
        critical_unscheduled=critical_unscheduled(scenario, config, assignments),
        moved_jobs=moved_jobs(prev_assignments, assignments, now),
    )
    plan.explanations = explain(scenario, plan, fixed_ids=fixed_ids)
    return plan
