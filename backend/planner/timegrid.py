"""1-hour time grid: crew shift hours and the feasible slots for a job.

A job needs ``repair_hours`` on-shift hours from one crew. If it does not
finish within one shift it pauses off-shift and resumes at the next shift, so
its wall-clock interval ``[start, end)`` can span nights. A job may not
overlap a crew's unavailability, and a shutdown-only job must sit entirely
inside one shutdown window.
"""

from __future__ import annotations

from .models import Crew, Defect, Scenario


def shift_hours(crew: Crew, horizon_hours: int) -> list[bool]:
    """For each hour of the horizon, True if the crew is on shift."""
    on = []
    for h in range(horizon_hours):
        day, hour = divmod(h, 24)
        worked = crew.work_days is None or day in crew.work_days
        on.append(worked and crew.shift_start <= hour < crew.shift_start + crew.shift_hours)
    return on


def end_table(on_shift: list[bool], duration: int) -> dict[int, int]:
    """Map each on-shift start hour to the wall-clock end after ``duration`` on-shift hours.

    Starts whose job would run past the horizon are omitted.
    """
    working = [h for h, on in enumerate(on_shift) if on]
    return {
        working[k]: working[k + duration - 1] + 1
        for k in range(len(working) - duration + 1)
    }


def release_hour(defect: Defect, scenario: Scenario, now: int) -> int:
    """Earliest hour work may start: after ``now`` and after the permit lead time."""
    permit = scenario.permit(defect.permit)
    lead = permit.lead_hours if permit else 0
    return max(now, defect.found_at + lead)


def feasible_slots(
    defect: Defect,
    crew: Crew,
    scenario: Scenario,
    release: int,
    *,
    shutdown: bool = True,
    unavailability: bool = True,
) -> dict[int, int]:
    """Feasible ``{start: end}`` slots for one defect on one crew, ignoring other jobs.

    ``shutdown`` and ``unavailability`` switch those filters off, which the
    explainer uses to find out which constraint delayed a job.
    """
    if defect.skill not in crew.skills:
        return {}
    table = end_table(shift_hours(crew, scenario.horizon_hours), defect.repair_hours)
    slots = {}
    for s, e in table.items():
        if s < release:
            continue
        if shutdown and defect.needs_shutdown and not any(w.start <= s and e <= w.end for w in scenario.windows):
            continue
        if unavailability and any(u.overlaps(s, e) for u in crew.unavailable):
            continue
        slots[s] = e
    return slots


def window_containing(scenario: Scenario, start: int, end: int) -> str | None:
    """Id of the shutdown window that contains ``[start, end)``, if any."""
    return next((w.id for w in scenario.windows if w.start <= start and end <= w.end), None)
