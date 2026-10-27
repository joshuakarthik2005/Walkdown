import pytest
from pydantic import ValidationError

from backend.planner.models import Crew, Defect, PermitType, Scenario, ShutdownWindow, TimeRange
from backend.planner.timegrid import end_table, feasible_slots, release_hour, shift_hours


def _scenario(**kw) -> Scenario:
    base = dict(
        name="t",
        horizon_days=3,
        defects=[Defect(id="d1", asset="A", severity=3, failure_risk=0.5, repair_hours=4, skill="coating")],
        crews=[Crew(id="c1", skills=["coating"])],
    )
    base.update(kw)
    return Scenario(**base)


def test_shift_hours_default_day_shift():
    on = shift_hours(Crew(id="c", skills=["x"]), 48)
    assert [h for h, v in enumerate(on) if v] == list(range(8, 16)) + list(range(32, 40))


def test_end_table_pauses_overnight():
    on = shift_hours(Crew(id="c", skills=["x"]), 48)
    table = end_table(on, 10)
    # Start 08:00 day 0: 8 h on day 0, remaining 2 h on day 1 (08-10).
    assert table[8] == 24 + 10
    # Start 15:00 day 0: 1 h, then 9 h needed on day 1 but only 8 available, and horizon ends.
    assert 15 not in table


def test_release_includes_permit_lead_time():
    sc = _scenario(
        defects=[Defect(id="d1", asset="A", severity=3, failure_risk=0.5, repair_hours=4, skill="coating",
                        permit="hot", found_at=2)],
        permits=[PermitType(id="hot", lead_hours=24)],
    )
    assert release_hour(sc.defects[0], sc, now=0) == 26
    assert release_hour(sc.defects[0], sc, now=40) == 40


def test_shutdown_job_must_fit_inside_window():
    d = Defect(id="d1", asset="A", severity=3, failure_risk=0.5, repair_hours=4, skill="coating", needs_shutdown=True)
    sc = _scenario(defects=[d], windows=[ShutdownWindow(id="w1", start=34, end=40)])
    slots = feasible_slots(d, sc.crews[0], sc, release=0)
    assert slots == {34: 38, 35: 39, 36: 40}
    assert len(feasible_slots(d, sc.crews[0], sc, release=0, shutdown=False)) > 3


def test_unavailability_blocks_overlapping_slots():
    crew = Crew(id="c1", skills=["coating"], unavailable=[TimeRange(start=10, end=12)])
    sc = _scenario(crews=[crew])
    slots = feasible_slots(sc.defects[0], crew, sc, release=0)
    assert all(not (s < 12 and 10 < e) for s, e in slots.items())
    assert 12 in slots and 8 not in slots


def test_skill_mismatch_has_no_slots():
    sc = _scenario(crews=[Crew(id="c1", skills=["welding"])])
    assert feasible_slots(sc.defects[0], sc.crews[0], sc, release=0) == {}


def test_scenario_rejects_unknown_permit_and_duplicates():
    with pytest.raises(ValidationError):
        _scenario(defects=[Defect(id="d1", asset="A", severity=1, failure_risk=0.1, repair_hours=1,
                                  skill="coating", permit="nope")])
    with pytest.raises(ValidationError):
        _scenario(crews=[Crew(id="c1", skills=["coating"]), Crew(id="c1", skills=["coating"])])


def test_crew_shift_cannot_cross_midnight():
    with pytest.raises(ValidationError):
        Crew(id="c", skills=["x"], shift_start=20, shift_hours=8)
