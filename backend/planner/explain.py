"""Structured explanations of a plan, one per defect.

For a scheduled job, the delay from ``now`` to its start is split into
causes by re-running the feasible-slot search with filters switched on one
at a time:

    release (now, permit lead time)
    -> earliest on-shift start            OUTSIDE_SHIFT
    -> earliest start inside a window     WAITING_FOR_SHUTDOWN_WINDOW
    -> earliest start avoiding crew leave CREW_UNAVAILABLE
    -> actual start                       CREW_CAPACITY / PERMIT_CONCURRENCY / DEFERRED_BY_OPTIMISER

For an unscheduled defect, the first filter that leaves no slot at all is
reported; if slots exist, the defect was crowded out by other work.
The output is data, not prose: Muse Spark narrates it later.
"""

from __future__ import annotations

from .models import DefectExplanation, Plan, PlannerConfig, Reason, ReasonCode, Scenario
from .timegrid import feasible_slots, release_hour, shift_hours, window_containing


def _capacity_detail(scenario: Scenario, plan: Plan, defect, eligible, release: int) -> dict:
    """Crew-hour arithmetic behind a crowded-out defect: skilled hours left vs hours the job needs."""
    horizon = scenario.horizon_hours
    available = booked = 0
    for c in eligible:
        on = shift_hours(c, horizon)
        free = {h for h in range(release, horizon) if on[h] and not any(u.start <= h < u.end for u in c.unavailable)}
        busy = {h for a in plan.assignments if a.crew_id == c.id for h in range(max(a.start, release), a.end)}
        available += len(free)
        booked += len(free & busy)
    unscheduled = set(plan.unscheduled)
    return dict(skill=defect.skill, eligible_crews=sorted(c.id for c in eligible), repair_hours=defect.repair_hours,
                skilled_crew_hours_from_release=available, skilled_crew_hours_booked=booked,
                skilled_crew_hours_free=available - booked,
                unscheduled_same_skill_hours=sum(x.repair_hours for x in scenario.defects
                                                 if x.id in unscheduled and x.skill == defect.skill),
                summary=(f"not enough {defect.skill} crew hours in the horizon: all {available} {defect.skill} crew hours "
                         f"from release to the horizon end are booked with higher-risk work"
                         if available - booked <= 0 else
                         f"not enough {defect.skill} crew hours in the horizon: only {available - booked} of {available} "
                         f"{defect.skill} crew hours are free, in gaps too short or too late for this "
                         f"{defect.repair_hours} h job"))


def explain(scenario: Scenario, plan: Plan, *, fixed_ids: set[str] | None = None,
            config: PlannerConfig | None = None) -> list[DefectExplanation]:
    """Explain why each defect is scheduled where it is, or why it is unscheduled."""
    fixed_ids = fixed_ids or set()
    config = config or PlannerConfig()
    now = plan.now
    out = []
    for d in scenario.defects:
        a = plan.assignment(d.id)
        release = release_hour(d, scenario, now)
        eligible = [c for c in scenario.crews if c.can_do(d)]

        def earliest(r: int, shutdown: bool, unavailability: bool) -> int | None:
            starts = [min(sl) for c in eligible
                      if (sl := feasible_slots(d, c, scenario, r, shutdown=shutdown, unavailability=unavailability))]
            return min(starts) if starts else None

        if a is not None and d.id in fixed_ids:
            in_progress = a.end > now
            out.append(DefectExplanation(
                defect_id=d.id, status="in_progress" if in_progress else "completed",
                crew_id=a.crew_id, start=a.start, end=a.end, release_hour=a.start,
                earliest_feasible_start=a.start,
                reasons=[Reason(code=ReasonCode.WORK_IN_PROGRESS, until_hour=a.end)] if in_progress else [],
            ))
            continue

        permit = scenario.permit(d.permit)
        permit_ready = d.found_at + (permit.lead_hours if permit else 0)
        e_shift = earliest(release, False, False)
        e_shut = earliest(release, True, False)
        e_full = earliest(release, True, True)
        leave_crews = sorted(c.id for c in eligible if c.unavailable)

        if a is None:
            if not eligible:
                reason = Reason(code=ReasonCode.NO_SKILLED_CREW, related_ids=[d.skill])
            elif earliest(max(now, d.found_at), False, False) is None:
                reason = Reason(code=ReasonCode.DOES_NOT_FIT_IN_HORIZON)
            elif e_shift is None:
                reason = Reason(code=ReasonCode.PERMIT_NOT_READY_IN_HORIZON, until_hour=permit_ready,
                                related_ids=[d.permit] if d.permit else [])
            elif e_shut is None:
                reason = Reason(code=ReasonCode.NO_SHUTDOWN_WINDOW_FITS, related_ids=[w.id for w in scenario.windows])
            elif e_full is None:
                reason = Reason(code=ReasonCode.CREW_UNAVAILABLE, related_ids=leave_crews)
            else:
                reason = Reason(code=ReasonCode.CROWDED_OUT, related_ids=sorted(c.id for c in eligible),
                                detail=_capacity_detail(scenario, plan, d, eligible, release))
            out.append(DefectExplanation(defect_id=d.id, status="unscheduled", release_hour=release,
                                         earliest_feasible_start=e_full, reasons=[reason]))
            continue

        reasons = []
        if permit_ready > now:
            reasons.append(Reason(code=ReasonCode.PERMIT_LEAD_TIME, delay_hours=permit_ready - now,
                                  until_hour=permit_ready, related_ids=[d.permit]))
        if e_shift > release:
            reasons.append(Reason(code=ReasonCode.OUTSIDE_SHIFT, delay_hours=e_shift - release, until_hour=e_shift))
        if e_shut > e_shift:
            window = window_containing(scenario, a.start, a.end)
            reasons.append(Reason(code=ReasonCode.WAITING_FOR_SHUTDOWN_WINDOW, delay_hours=e_shut - e_shift,
                                  until_hour=e_shut, related_ids=[window] if window else []))
        if e_full > e_shut:
            reasons.append(Reason(code=ReasonCode.CREW_UNAVAILABLE, delay_hours=e_full - e_shut,
                                  until_hour=e_full, related_ids=leave_crews))
        if a.start > e_full:
            eligible_ids = {c.id for c in eligible}
            others = [b for b in plan.assignments if b.defect_id != d.id and b.start < a.start and b.end > e_full]
            crew_block = sorted(b.defect_id for b in others if b.crew_id in eligible_ids)
            permit_block = []
            if permit is not None and permit.max_concurrent is not None:
                permit_block = sorted(b.defect_id for b in others if scenario.defect(b.defect_id).permit == d.permit)
            delay = a.start - e_full
            if crew_block:
                reasons.append(Reason(code=ReasonCode.CREW_CAPACITY, delay_hours=delay,
                                      until_hour=a.start, related_ids=crew_block))
            if permit_block:
                reasons.append(Reason(code=ReasonCode.PERMIT_CONCURRENCY, delay_hours=delay,
                                      until_hour=a.start, related_ids=permit_block))
            if not crew_block and not permit_block:
                reasons.append(Reason(code=ReasonCode.DEFERRED_BY_OPTIMISER, delay_hours=delay, until_hour=a.start))
        if not reasons:
            reasons.append(Reason(code=ReasonCode.ON_EARLIEST_POSSIBLE))
        out.append(DefectExplanation(defect_id=d.id, status="scheduled", crew_id=a.crew_id, start=a.start,
                                     end=a.end, release_hour=release, earliest_feasible_start=e_full,
                                     reasons=reasons))
    for e in out:  # why this defect ranks where it does: likelihood x consequence of its line service
        d = scenario.defect(e.defect_id)
        e.priority = dict(service=d.service.value if d.service else None, severity=d.severity,
                          likelihood=round(config.likelihood(d), 3), consequence_factor=config.consequence(d),
                          risk_weight=config.risk_weight(d), critical=config.is_critical(d), high=config.is_high(d))
    return out
