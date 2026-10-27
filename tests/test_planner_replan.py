import pytest

from backend.planner.cpsat import solve
from backend.planner.generator import generate_scenario
from backend.planner.metrics import moved_jobs, validate
from backend.planner.models import CrewUnavailable, Defect, NewDefect, PlannerConfig, ReasonCode, \
    ShutdownWindowChanged
from backend.planner.replan import apply_change, replan
from backend.planner.timegrid import window_containing

CONFIG = PlannerConfig(time_limit_s=5)
NOW = 40


@pytest.fixture(scope="module")
def base():
    sc = generate_scenario(7, name="demo")
    return sc, solve(sc, CONFIG)


def _started(plan):
    return {a.defect_id for a in plan.assignments if a.start < NOW}


def _check_common(sc_before, plan_before, result):
    fixed = _started(plan_before)
    assert fixed, "fixture should have work in progress at NOW"
    for did in fixed:
        assert result.plan.assignment(did) == plan_before.assignment(did)
    assert validate(result.scenario, result.plan.assignments, now=NOW, fixed_ids=fixed) == []
    assert result.moved_jobs == moved_jobs(plan_before.assignments, result.plan.assignments, NOW)
    for a in result.plan.assignments:
        if a.defect_id not in fixed:
            assert a.start >= NOW


def test_crew_unavailable(base):
    sc, plan = base
    crew = max(sc.crews, key=lambda c: sum(a.crew_id == c.id for a in plan.assignments)).id
    result = replan(sc, plan, CrewUnavailable(crew_id=crew, start=NOW, end=NOW + 72), now=NOW, config=CONFIG)
    _check_common(sc, plan, result)
    fixed = _started(plan)
    assert not any(a.crew_id == crew and a.start < NOW + 72 and a.end > NOW
                   for a in result.plan.assignments if a.defect_id not in fixed)
    assert result.moved_jobs, "taking the busiest crew away for 3 days should move work"


def test_shutdown_window_moved(base):
    sc, plan = base
    result = replan(sc, plan, ShutdownWindowChanged(window_id="SD1", new_start=130, new_end=178), now=NOW,
                    config=CONFIG)
    _check_common(sc, plan, result)
    for a in result.plan.assignments:
        if result.scenario.defect(a.defect_id).needs_shutdown and a.defect_id not in _started(plan):
            assert window_containing(result.scenario, a.start, a.end) is not None


def test_all_shutdown_windows_cancelled_in_two_replans(base):
    sc, plan = base
    first = replan(sc, plan, ShutdownWindowChanged(window_id="SD1"), now=NOW, config=CONFIG)
    second = replan(first.scenario, first.plan, ShutdownWindowChanged(window_id="SD2"), now=NOW, config=CONFIG)
    assert second.scenario.windows == []
    reasons = {e.defect_id: e for e in second.plan.explanations}
    for d in second.scenario.defects:
        if d.needs_shutdown and d.id not in _started(plan):
            assert d.id in second.plan.unscheduled
            assert reasons[d.id].reasons[0].code == ReasonCode.NO_SHUTDOWN_WINDOW_FITS


def test_new_critical_defect_is_scheduled(base):
    sc, plan = base
    new = Defect(id="N1", asset="TANK-1", severity=5, failure_risk=0.9, repair_hours=6, skill="welding",
                 permit="hot_work")
    result = replan(sc, plan, NewDefect(defect=new), now=NOW, config=CONFIG)
    _check_common(sc, plan, result)
    a = result.plan.assignment("N1")
    assert a is not None and a.start >= NOW + 24  # hot-work permit lead time counts from discovery
    assert result.scenario.defect("N1").found_at == NOW
    assert "N1" not in result.plan.critical_unscheduled
    assert result.newly_scheduled == ["N1"]


def test_move_penalty_keeps_plan_stable(base):
    sc, plan = base
    change = CrewUnavailable(crew_id="C1", start=NOW, end=NOW + 48)
    loose = replan(sc, plan, change, now=NOW, config=CONFIG.model_copy(update={"move_penalty": 0}))
    tight = replan(sc, plan, change, now=NOW, config=CONFIG.model_copy(update={"move_penalty": 100_000}))
    assert len(tight.moved_jobs) <= len(loose.moved_jobs)


def test_invalid_changes_rejected(base):
    sc, plan = base
    with pytest.raises(ValueError):
        apply_change(sc, ShutdownWindowChanged(window_id="nope"), NOW)
    with pytest.raises(ValueError):
        apply_change(sc, ShutdownWindowChanged(window_id="SD1", new_start=10), NOW)
    with pytest.raises(ValueError):
        apply_change(sc, NewDefect(defect=sc.defects[0]), NOW)
    later = plan.model_copy(update={"now": 100})
    with pytest.raises(ValueError):
        replan(sc, later, CrewUnavailable(crew_id="C1", start=0, end=10), now=NOW)
