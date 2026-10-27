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
+ critical_penalty x unscheduled critical defects (severity 5)
+ high_penalty x unscheduled high-priority defects (severity 4)
+ move_penalty x previously planned jobs that move (replanning only).

Replanning: jobs from ``previous`` that started before ``now`` are fixed.
With ``config.lexicographic_replan`` (default) the replan is solved in two
stages instead of with a move penalty:
  stage 1: minimise exposure + unscheduled penalties;
  stage 2: keep that objective <= stage-1 value x (1 + replan_epsilon) and
           minimise move_job_weight x moved jobs + hours displaced.
Stage 2 is warm-started from the stage-1 solution. The time limit is split
between the stages (``stage1_time_share``).

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
        hint = priority_sort(scenario, config, now=now, previous=previous, keep_previous=True).assignments
    horizon = scenario.horizon_hours
    model = cp_model.CpModel()

    fixed = fixed_jobs(scenario, previous, now)
    fixed_ids = {a.defect_id for a in fixed}
    planned_before = {a.defect_id: a for a in (previous.assignments if previous else []) if a.start >= now}

    crew_intervals: dict[str, list] = defaultdict(list)
    permit_intervals: dict[str, list] = defaultdict(list)
    crew_load: dict[str, list] = defaultdict(list)  # (presence, repair hours) per crew, for symmetry breaking
    for a in fixed:
        iv = model.new_interval_var(a.start, a.end - a.start, a.end, f"fixed_{a.defect_id}")
        crew_intervals[a.crew_id].append(iv)
        permit = scenario.defect(a.defect_id).permit
        if permit:
            permit_intervals[permit].append(iv)

    # option = (crew_id, presence, start, end, span, feasible {start: end})
    options: dict[str, list[tuple[str, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar,
                                  dict[int, int]]]] = {}
    unscheduled_lit: dict[str, cp_model.IntVar] = {}
    completion_var: dict[str, cp_model.IntVar] = {}
    same_var: dict[str, tuple[cp_model.IntVar, str, int]] = {}
    primary = []  # exposure + unscheduled penalties
    move_terms = []  # 1 per moved job (legacy single-stage penalty)
    stability = []  # stage-2 objective terms
    displacement: dict[str, tuple[cp_model.IntVar, int]] = {}
    lexicographic = previous is not None and config.lexicographic_replan and bool(planned_before)

    for d in scenario.defects:
        weight = config.risk_weight(d)
        if d.id in fixed_ids:
            end = next(a.end for a in fixed if a.defect_id == d.id)
            primary.append(weight * (end - d.found_at))
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
            crew_load[c.id].append((x, d.repair_hours))
            opts.append((c.id, x, s, e, span, slots))
        options[d.id] = opts

        u = model.new_bool_var(f"u_{d.id}")
        unscheduled_lit[d.id] = u
        model.add_exactly_one([o[1] for o in opts] + [u])

        completion = model.new_int_var(0, horizon, f"C_{d.id}")
        completion_var[d.id] = completion
        for _, x, _, e, _, _ in opts:
            model.add(completion == e).only_enforce_if(x)
        model.add(completion == horizon).only_enforce_if(u)
        primary.append(weight * (completion - d.found_at))
        if config.unscheduled_penalty(d):
            primary.append(config.unscheduled_penalty(d) * u)

        prev = planned_before.get(d.id)
        if prev is not None:
            match = next((o for o in opts if o[0] == prev.crew_id), None)
            if match is not None and prev.start in feasible_slots(d, scenario.crew(prev.crew_id), scenario, release):
                same = model.new_bool_var(f"same_{d.id}")
                model.add_implication(same, match[1])
                model.add(match[2] == prev.start).only_enforce_if(same)
                move_terms.append(1 - same)
                same_var[d.id] = (same, prev.crew_id, prev.start)
            else:
                move_terms.append(1)
            if lexicographic:
                # Hours the start moves; a dropped job counts as moved to the horizon end.
                disp = model.new_int_var(0, horizon, f"disp_{d.id}")
                for _, x, s, _, _, _ in opts:
                    model.add(disp >= s - prev.start).only_enforce_if(x)
                    model.add(disp >= prev.start - s).only_enforce_if(x)
                model.add(disp >= horizon - prev.start).only_enforce_if(u)
                displacement[d.id] = (disp, prev.start)
                stability.append(config.move_job_weight * move_terms[-1] + disp)

    for ivs in crew_intervals.values():
        model.add_no_overlap(ivs)

    # Symmetry breaking: interchangeable crews (same skills, shift and calendar, no leave, nothing fixed or
    # previously planned) are ordered by booked hours, so CP-SAT does not explore relabelled copies.
    symmetric_groups = [] if (fixed or planned_before) else identical_crew_groups(scenario)
    for group in symmetric_groups:
        for a, b in zip(group, group[1:]):
            model.add(sum(h * x for x, h in crew_load[a]) >= sum(h * x for x, h in crew_load[b]))
    if hint and symmetric_groups:
        hint = relabel_hint_for_symmetry(hint, symmetric_groups, scenario)
    for permit_id, ivs in permit_intervals.items():
        cap = scenario.permit(permit_id).max_concurrent
        if cap is not None:
            model.add_cumulative(ivs, [1] * len(ivs), cap)

    if lexicographic:
        model.minimize(sum(primary))
    else:
        model.minimize(sum(primary) + config.move_penalty * sum(move_terms))

    if hint:
        # A complete hint (every variable) lets CP-SAT accept the warm start as its
        # first solution; with a partial hint it may discard it.
        hinted = {a.defect_id: a for a in hint}
        for did, opts in options.items():
            h = hinted.get(did)
            chosen = next((o for o in opts if h is not None and o[0] == h.crew_id and o[5].get(h.start) == h.end), None)
            for o in opts:
                crew_id, x, s, e, span, slots = o
                hs = h.start if o is chosen else min(slots)
                model.add_hint(x, o is chosen)
                model.add_hint(s, hs)
                model.add_hint(e, slots[hs])
                model.add_hint(span, slots[hs] - hs)
            model.add_hint(unscheduled_lit[did], chosen is None)
            model.add_hint(completion_var[did], h.end if chosen else horizon)
            if did in same_var:
                same, crew_id, start_ = same_var[did]
                model.add_hint(same, chosen is not None and h.crew_id == crew_id and h.start == start_)
            if did in displacement:
                disp, p_start = displacement[did]
                model.add_hint(disp, abs(h.start - p_start) if chosen else horizon - p_start)

    def run(limit: float) -> tuple[cp_model.CpSolver, int]:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = limit
        solver.parameters.num_workers = config.num_workers
        solver.parameters.random_seed = config.random_seed
        solver.parameters.cp_model_probing_level = config.probing_level
        return solver, solver.solve(model)

    def extract(solver: cp_model.CpSolver) -> list[Assignment]:
        out = list(fixed)
        for did, opts in options.items():
            for crew_id, x, s, e, _, _ in opts:
                if solver.boolean_value(x):
                    out.append(Assignment(defect_id=did, crew_id=crew_id, start=solver.value(s), end=solver.value(e)))
        return out

    ok = (cp_model.OPTIMAL, cp_model.FEASIBLE)
    stage1_limit = config.time_limit_s * (config.stage1_time_share if lexicographic else 1.0)
    solver, status = run(stage1_limit)
    status_name = solver.status_name(status)

    if status not in ok:
        if status != cp_model.UNKNOWN or not hint:
            raise RuntimeError(f"CP-SAT returned {status_name} and there is no warm start to fall back on")
        stats = SolveStats(solver="cp-sat", status=status_name, fallback="warm_start", wall_time_s=solver.wall_time)
        plan = build_plan(scenario, config, list(hint), stats, now=now, previous=previous, fixed_ids=fixed_ids)
        plan.stats.objective = float(plan.breakdown.total)
        return plan

    objective_value = solver.objective_value
    bound = solver.best_objective_bound
    gap = abs(objective_value - bound) / max(1.0, abs(objective_value))
    assignments = extract(solver)
    wall = solver.wall_time

    if not lexicographic:
        stats = SolveStats(solver="cp-sat", status=status_name, objective=objective_value, best_bound=bound,
                           gap=gap, wall_time_s=wall)
        return build_plan(scenario, config, assignments, stats, now=now, previous=previous, fixed_ids=fixed_ids)

    stages = [dict(stage="risk", status=status_name, objective=objective_value, best_bound=bound, gap=gap,
                   wall_time_s=wall)]
    # Stage 2: hold risk within epsilon of stage 1 and minimise churn, warm-started from stage 1.
    model.add(sum(primary) <= int(objective_value * (1 + config.replan_epsilon)))
    model.clear_hints()
    for i in range(len(model.proto.variables)):
        var = model.get_int_var_from_proto_index(i)
        model.add_hint(var, solver.value(var))
    model.minimize(sum(stability))
    solver2, status2 = run(max(0.5, config.time_limit_s - wall))
    stage2_name = solver2.status_name(status2)
    stages.append(dict(stage="stability", status=stage2_name,
                       objective=solver2.objective_value if status2 in ok else None,
                       best_bound=solver2.best_objective_bound if status2 in ok else None,
                       wall_time_s=solver2.wall_time))
    if status2 in ok:
        assignments = extract(solver2)
    wall += solver2.wall_time
    overall = "OPTIMAL" if status == cp_model.OPTIMAL and status2 == cp_model.OPTIMAL else "FEASIBLE"
    stats = SolveStats(solver="cp-sat", status=overall, best_bound=bound, wall_time_s=wall, stages=stages)
    plan = build_plan(scenario, config, assignments, stats, now=now, previous=previous, fixed_ids=fixed_ids)
    # Reported objective = risk objective (exposure + penalties) of the final plan; bound and gap are stage 1's.
    risk = plan.breakdown.total - plan.breakdown.move_penalty
    plan.stats.objective = float(risk)
    plan.stats.gap = abs(risk - bound) / max(1.0, abs(risk))
    return plan


def identical_crew_groups(scenario: Scenario) -> list[list[str]]:
    """Groups (size >= 2) of crews that are interchangeable: same skills, shift, work days and no leave."""
    groups: dict[tuple, list[str]] = defaultdict(list)
    for c in scenario.crews:
        if c.unavailable:
            continue
        key = (tuple(sorted(c.skills)), c.shift_start, c.shift_hours, tuple(c.work_days or ()))
        groups[key].append(c.id)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def relabel_hint_for_symmetry(hint: list[Assignment], groups: list[list[str]], scenario: Scenario) -> list[Assignment]:
    """Swap identical crews' jobs in a warm start so it satisfies the symmetry-breaking order (busiest first)."""
    hours = {d.id: d.repair_hours for d in scenario.defects}
    rename: dict[str, str] = {}
    for group in groups:
        load = {c: sum(hours[a.defect_id] for a in hint if a.crew_id == c) for c in group}
        for new, old in zip(group, sorted(group, key=lambda c: (-load[c], c))):
            rename[old] = new
    return [a.model_copy(update={"crew_id": rename.get(a.crew_id, a.crew_id)}) for a in hint]
