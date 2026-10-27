from backend.planner.cpsat import solve
from backend.planner.generator import generate_scenario
from backend.planner.metrics import validate
from backend.planner.models import Crew, Defect, PermitType, PlannerConfig, Scenario, SolveStats

FAST = PlannerConfig(time_limit_s=5)


def _one_crew(defects, horizon_days=2, **kw) -> Scenario:
    return Scenario(name="h", horizon_days=horizon_days, defects=defects,
                    crews=[Crew(id="c", skills=["coating"])], **kw)


def test_higher_risk_job_goes_first_and_is_optimal():
    sc = _one_crew([
        Defect(id="low", asset="A", severity=2, failure_risk=0.2, repair_hours=4, skill="coating"),
        Defect(id="high", asset="B", severity=4, failure_risk=0.8, repair_hours=4, skill="coating"),
    ])
    plan = solve(sc, FAST)
    assert plan.stats.status == "OPTIMAL" and plan.stats.is_optimal
    assert plan.stats.gap == 0
    assert plan.assignment("high").start == 8 and plan.assignment("high").end == 12
    assert plan.assignment("low").start == 12
    assert validate(sc, plan.assignments) == []


def test_solver_objective_matches_shared_evaluator():
    sc = generate_scenario(11, n_defects=20)
    plan = solve(sc, FAST)
    assert plan.stats.objective == plan.breakdown.total
    assert validate(sc, plan.assignments) == []


def test_critical_penalty_forces_critical_job_into_scarce_slot():
    defects = [
        Defect(id="crit", asset="A", severity=5, failure_risk=0.05, repair_hours=8, skill="coating"),
        Defect(id="big", asset="B", severity=4, failure_risk=1.0, repair_hours=8, skill="coating"),
    ]
    sc = _one_crew(defects, horizon_days=1)
    assert solve(sc, PlannerConfig(critical_penalty=0)).unscheduled == ["crit"]
    plan = solve(sc, FAST)
    assert plan.unscheduled == ["big"] and plan.critical_unscheduled == []
    assert plan.high_unscheduled == ["big"]  # severity 4 is the "high" tier
    assert plan.breakdown.high_penalty == FAST.high_penalty and plan.breakdown.critical_penalty == 0


def test_high_penalty_tier_prefers_severity_4_over_riskier_severity_3():
    defects = [
        Defect(id="sev4", asset="A", severity=4, failure_risk=0.1, repair_hours=8, skill="coating"),
        Defect(id="sev3", asset="B", severity=3, failure_risk=1.0, repair_hours=8, skill="coating"),
    ]
    sc = _one_crew(defects, horizon_days=1)
    # Exposure alone favours the riskier severity-3 job (weight 400 vs 80).
    assert solve(sc, PlannerConfig(high_penalty=0, time_limit_s=5)).unscheduled == ["sev4"]
    plan = solve(sc, FAST)
    assert plan.unscheduled == ["sev3"] and plan.high_unscheduled == []
    assert plan.stats.objective == plan.breakdown.total


def test_permit_cap_and_lead_time_respected():
    sc = Scenario(
        name="p", horizon_days=3,
        defects=[Defect(id=f"d{i}", asset="A", severity=3, failure_risk=0.5, repair_hours=4, skill="welding",
                        permit="hot") for i in range(3)],
        crews=[Crew(id=f"c{i}", skills=["welding"]) for i in range(3)],
        permits=[PermitType(id="hot", lead_hours=24, max_concurrent=1)],
    )
    plan = solve(sc, FAST)
    assert validate(sc, plan.assignments) == []
    assert all(a.start >= 24 for a in plan.assignments)
    spans = sorted((a.start, a.end) for a in plan.assignments)
    assert all(b[0] >= a[1] for a, b in zip(spans, spans[1:]))


def test_time_limit_and_feasible_is_never_reported_optimal():
    assert not SolveStats(solver="cp-sat", status="FEASIBLE").is_optimal
    sc = generate_scenario(1, n_defects=40)
    plan = solve(sc, PlannerConfig(time_limit_s=1.0))
    assert plan.stats.wall_time_s < 5
    assert plan.stats.status in ("OPTIMAL", "FEASIBLE", "UNKNOWN")
    assert plan.stats.is_optimal == (plan.stats.status == "OPTIMAL")
    if plan.stats.status == "UNKNOWN":
        assert plan.stats.fallback == "warm_start" and plan.stats.best_bound is None
    else:
        assert plan.stats.fallback is None and plan.stats.best_bound <= plan.stats.objective
    assert validate(sc, plan.assignments) == []


def test_unknown_without_warm_start_raises():
    sc = generate_scenario(1, n_defects=40)
    try:
        plan = solve(sc, PlannerConfig(time_limit_s=0.05), warm_start=False)
    except RuntimeError as err:
        assert "no warm start" in str(err)
    else:  # a very fast machine may still find a solution
        assert plan.stats.status in ("OPTIMAL", "FEASIBLE")


def test_symmetry_breaking_on_identical_crews_keeps_optimum():
    from backend.planner.cpsat import identical_crew_groups
    sc = Scenario(
        name="sym", horizon_days=2,
        defects=[Defect(id=f"d{i}", asset="A", severity=3, failure_risk=0.5, repair_hours=4 + i, skill="coating")
                 for i in range(5)],
        crews=[Crew(id="c1", skills=["coating"]), Crew(id="c2", skills=["coating"]), Crew(id="c3", skills=["welding"])],
    )
    assert identical_crew_groups(sc) == [["c1", "c2"]]
    plan = solve(sc, FAST)
    load = {c: sum(a.end - a.start for a in plan.assignments if a.crew_id == c) for c in ("c1", "c2")}
    assert plan.stats.is_optimal and validate(sc, plan.assignments) == []
    hours = {d.id: d.repair_hours for d in sc.defects}
    booked = {c: sum(hours[a.defect_id] for a in plan.assignments if a.crew_id == c) for c in ("c1", "c2")}
    assert booked["c1"] >= booked["c2"]
