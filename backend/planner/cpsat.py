"""CP-SAT maintenance scheduler.

Decisions: for each defect, which eligible crew (if any) repairs it and when.

Model per (defect, eligible crew) option:
- presence literal ``x``; start variable whose domain is the precomputed
  feasible starts (shift hours, release, shutdown window, unavailability);
  end fixed by an element constraint over the wall-clock end table;
- an optional interval in that crew's no-overlap and, for capped permits,
  in that permit's cumulative.
Each defect takes exactly one option or the "unscheduled" literal.

Objective (all weights in ``PlannerConfig``):
  sum risk_weight x (completion - found_at)   unscheduled => completion = horizon
+ critical_penalty x unscheduled critical defects
+ move_penalty x previously planned jobs that move (replanning only).

Replanning: jobs from ``previous`` that started before ``now`` are fixed.

Warm start: by default the priority-sort plan is passed as a solution hint,
so CP-SAT starts from the baseline and only improves on it. If the time
limit expires before CP-SAT has any solution (status UNKNOWN), the warm-start
plan is returned with status UNKNOWN and ``fallback="warm_start"``; it is
never labelled as a CP-SAT solution.
"""

from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model

from .baseline import priority_sort
from .common import build_plan, fixed_jobs
from .models import Assignment, Plan, PlannerConfig, Scenario, SolveStats
from .timegrid import feasible_slots, release_hour


def solve(
    scenario: Scenario,
    config: PlannerConfig | None = None,
    *,
    now: int = 0,
    previous: Plan | None = None,
    hint: list[Assignment] | None = None,
    warm_start: bool = True,
) -> Plan:
    """Solve the scheduling problem and return a plan with stats and explanations.

    ``previous`` enables replanning: started jobs are fixed and moving other
    previously planned jobs costs ``config.move_penalty`` each. ``hint`` is a
    warm start; when omitted and ``warm_start`` is True the priority-sort plan is used.
    """
    config = config or PlannerConfig()
    if hint is None and warm_start:
        hint = priority_sort(scenario, config, now=now, previous=previous).assignments
    horizon = scenario.horizon_hours
    model = cp_model.CpModel()

    fixed = fixed_jobs(scenario, previous, now)
    fixed_ids = {a.defect_id for a in fixed}
    planned_before = {a.defect_id: a for a in (previous.assignments if previous else []) if a.start >= now}

    crew_intervals: dict[str, list] = defaultdict(list)
    permit_intervals: dict[str, list] = defaultdict(list)
    for a in fixed:
        iv = model.new_interval_var(a.start, a.end - a.start, a.end, f"fixed_{a.defect_id}")
        crew_intervals[a.crew_id].append(iv)
        permit = scenario.defect(a.defect_id).permit
        if permit:
            permit_intervals[permit].append(iv)

    options: dict[str, list[tuple[str, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]]] = {}
    unscheduled_lit: dict[str, cp_model.IntVar] = {}
    objective = []

    for d in scenario.defects:
        weight = config.risk_weight(d)
        if d.id in fixed_ids:
            end = next(a.end for a in fixed if a.defect_id == d.id)
            objective.append(weight * (end - d.found_at))
            continue

        release = release_hour(d, scenario, now)
        opts = []
        for c in scenario.crews:
            slots = feasible_slots(d, c, scenario, release)
            if not slots:
                continue
            starts = sorted(slots)
            table = [slots.get(s, 0) for s in range(starts[-1] + 1)]
            tag = f"{d.id}_{c.id}"
            x = model.new_bool_var(f"x_{tag}")
            s = model.new_int_var_from_domain(cp_model.Domain.from_values(starts), f"s_{tag}")
            e = model.new_int_var(min(slots.values()), max(slots.values()), f"e_{tag}")
            model.add_element(s, table, e)
            spans = [e_ - s_ for s_, e_ in slots.items()]
            span = model.new_int_var(min(spans), max(spans), f"span_{tag}")  # wall-clock, incl. off-shift
            model.add(span == e - s)
            iv = model.new_optional_interval_var(s, span, e, x, f"iv_{tag}")
            crew_intervals[c.id].append(iv)
            if d.permit and scenario.permit(d.permit).max_concurrent is not None:
                permit_intervals[d.permit].append(iv)
            opts.append((c.id, x, s, e))
        options[d.id] = opts

        u = model.new_bool_var(f"u_{d.id}")
        unscheduled_lit[d.id] = u
        model.add_exactly_one([o[1] for o in opts] + [u])

        completion = model.new_int_var(0, horizon, f"C_{d.id}")
        for _, x, _, e in opts:
            model.add(completion == e).only_enforce_if(x)
        model.add(completion == horizon).only_enforce_if(u)
        objective.append(weight * (completion - d.found_at))
        if config.is_critical(d):
            objective.append(config.critical_penalty * u)

        prev = planned_before.get(d.id)
        if prev is not None:
            match = next((o for o in opts if o[0] == prev.crew_id), None)
            if match is not None and prev.start in feasible_slots(d, scenario.crew(prev.crew_id), scenario, release):
                same = model.new_bool_var(f"same_{d.id}")
                model.add_implication(same, match[1])
                model.add(match[2] == prev.start).only_enforce_if(same)
                objective.append(config.move_penalty * (1 - same))
            else:
                objective.append(config.move_penalty)

    for ivs in crew_intervals.values():
        model.add_no_overlap(ivs)
    for permit_id, ivs in permit_intervals.items():
        cap = scenario.permit(permit_id).max_concurrent
        if cap is not None:
            model.add_cumulative(ivs, [1] * len(ivs), cap)

    model.minimize(sum(objective))

    if hint:
        hinted = {a.defect_id: a for a in hint}
        for did, opts in options.items():
            h = hinted.get(did)
            for crew_id, x, s, e in opts:
                on = h is not None and h.crew_id == crew_id
                model.add_hint(x, on)
                if on:
                    model.add_hint(s, h.start)
                    model.add_hint(e, h.end)
            model.add_hint(unscheduled_lit[did], h is None or all(o[0] != h.crew_id for o in opts))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_s
    solver.parameters.num_workers = config.num_workers
    solver.parameters.random_seed = config.random_seed
    status = solver.solve(model)
    status_name = solver.status_name(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status != cp_model.UNKNOWN or not hint:
            raise RuntimeError(f"CP-SAT returned {status_name} and there is no warm start to fall back on")
        stats = SolveStats(solver="cp-sat", status=status_name, fallback="warm_start", wall_time_s=solver.wall_time)
        plan = build_plan(scenario, config, list(hint), stats, now=now, previous=previous, fixed_ids=fixed_ids)
        plan.stats.objective = float(plan.breakdown.total)
        return plan

    assignments = list(fixed)
    for did, opts in options.items():
        for crew_id, x, s, e in opts:
            if solver.boolean_value(x):
                assignments.append(Assignment(defect_id=did, crew_id=crew_id,
                                              start=solver.value(s), end=solver.value(e)))
    assignments.sort(key=lambda a: (a.start, a.crew_id))

    objective_value = solver.objective_value
    bound = solver.best_objective_bound
    stats = SolveStats(
        solver="cp-sat",
        status=status_name,
        objective=objective_value,
        best_bound=bound,
        gap=abs(objective_value - bound) / max(1.0, abs(objective_value)),
        wall_time_s=solver.wall_time,
    )
    return build_plan(scenario, config, assignments, stats, now=now, previous=previous, fixed_ids=fixed_ids)
