import json

from backend.planner.cpsat import solve
from backend.planner.generator import generate_scenario
from backend.planner.models import CrewUnavailable, Crew, Defect, PermitType, PlannerConfig, ReasonCode, \
    Scenario, ShutdownWindow, TimeRange
from backend.planner.replan import replan

CONFIG = PlannerConfig(time_limit_s=5)


def _d(id_, **kw) -> Defect:
    base = dict(asset="A", severity=3, failure_risk=0.5, repair_hours=4, skill="coating")
    base.update(kw)
    return Defect(id=id_, **base)


def _explain(sc: Scenario, **kw):
    plan = solve(sc, CONFIG, **kw)
    return plan, {e.defect_id: e for e in plan.explanations}


def _codes(e):
    return [r.code for r in e.reasons]


def test_permit_lead_time_and_shutdown_wait():
    sc = Scenario(
        name="e", horizon_days=4,
        defects=[_d("p", permit="hot"), _d("w", needs_shutdown=True)],
        crews=[Crew(id="c1", skills=["coating"]), Crew(id="c2", skills=["coating"])],
        windows=[ShutdownWindow(id="SD1", start=56, end=72)],
        permits=[PermitType(id="hot", lead_hours=24)],
    )
    _, ex = _explain(sc)
    permit = next(r for r in ex["p"].reasons if r.code == ReasonCode.PERMIT_LEAD_TIME)
    assert permit.delay_hours == 24 and permit.until_hour == 24 and permit.related_ids == ["hot"]
    assert ex["p"].start == 32  # next shift after the permit is ready
    wait = next(r for r in ex["w"].reasons if r.code == ReasonCode.WAITING_FOR_SHUTDOWN_WINDOW)
    assert wait.until_hour == 56 and wait.related_ids == ["SD1"]


def test_crew_capacity_names_the_blocking_job():
    sc = Scenario(name="e", horizon_days=2, defects=[_d("first", severity=5), _d("second", severity=1)],
                  crews=[Crew(id="c", skills=["coating"])])
    _, ex = _explain(sc)
    cap = next(r for r in ex["second"].reasons if r.code == ReasonCode.CREW_CAPACITY)
    assert cap.related_ids == ["first"] and cap.delay_hours == 4
    assert _codes(ex["first"]) == [ReasonCode.OUTSIDE_SHIFT]


def test_crew_unavailable_delay():
    sc = Scenario(name="e", horizon_days=3, defects=[_d("x")],
                  crews=[Crew(id="c", skills=["coating"], unavailable=[TimeRange(start=0, end=30)])])
    _, ex = _explain(sc)
    assert ReasonCode.CREW_UNAVAILABLE in _codes(ex["x"])
    assert ex["x"].start == 32


def test_unscheduled_reasons():
    sc = Scenario(
        name="e", horizon_days=1,
        defects=[
            _d("noskill", skill="welding"),
            _d("toolong", repair_hours=20),
            _d("permit", permit="slow"),
            _d("a", severity=4), _d("b", severity=4), _d("c", severity=1),
        ],
        crews=[Crew(id="c", skills=["coating"])],
        permits=[PermitType(id="slow", lead_hours=48)],
    )
    plan, ex = _explain(sc)
    assert _codes(ex["noskill"]) == [ReasonCode.NO_SKILLED_CREW]
    assert _codes(ex["toolong"]) == [ReasonCode.DOES_NOT_FIT_IN_HORIZON]
    assert _codes(ex["permit"]) == [ReasonCode.PERMIT_NOT_READY_IN_HORIZON]
    assert _codes(ex["c"]) == [ReasonCode.CROWDED_OUT] and ex["c"].status == "unscheduled"
    assert ex["c"].earliest_feasible_start == 8


def test_no_shutdown_window_fits():
    sc = Scenario(name="e", horizon_days=2, defects=[_d("s", needs_shutdown=True, repair_hours=6)],
                  crews=[Crew(id="c", skills=["coating"])], windows=[ShutdownWindow(id="SD1", start=8, end=12)])
    _, ex = _explain(sc)
    assert _codes(ex["s"]) == [ReasonCode.NO_SHUTDOWN_WINDOW_FITS]


def test_every_defect_explained_and_json_serialisable_after_replan():
    sc = generate_scenario(7, name="demo")
    plan = solve(sc, CONFIG)
    result = replan(sc, plan, CrewUnavailable(crew_id="C1", start=40, end=88), now=40, config=CONFIG)
    ex = result.plan.explanations
    assert sorted(e.defect_id for e in ex) == sorted(d.id for d in result.scenario.defects)
    in_progress = [e for e in ex if e.status == "in_progress"]
    assert in_progress and all(_codes(e) == [ReasonCode.WORK_IN_PROGRESS] for e in in_progress)
    data = json.loads(result.plan.model_dump_json())
    assert all(isinstance(r["code"], str) for e in data["explanations"] for r in e["reasons"])
