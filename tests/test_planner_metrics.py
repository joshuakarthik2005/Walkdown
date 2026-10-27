from backend.planner.generator import SKILLS, generate_scenario
from backend.planner.metrics import crew_utilisation, evaluate, moved_jobs, validate
from backend.planner.models import Assignment, Crew, Defect, PlannerConfig, Scenario, ShutdownWindow


def _two_defects() -> Scenario:
    return Scenario(
        name="m",
        horizon_days=2,
        defects=[
            Defect(id="a", asset="X", severity=5, failure_risk=0.5, repair_hours=2, skill="coating"),
            Defect(id="b", asset="Y", severity=1, failure_risk=0.5, repair_hours=2, skill="coating",
                   needs_shutdown=True),
        ],
        crews=[Crew(id="c", skills=["coating"])],
        windows=[ShutdownWindow(id="w", start=32, end=40)],
    )


def test_generator_is_deterministic_and_covers_skills():
    a, b = generate_scenario(3), generate_scenario(3)
    assert a == b
    assert generate_scenario(4) != a
    covered = {s for c in a.crews for s in c.skills}
    assert set(SKILLS) <= covered


def test_evaluate_counts_unscheduled_to_horizon_and_critical_penalty():
    sc, cfg = _two_defects(), PlannerConfig()
    breakdown = evaluate(sc, cfg, [])
    wa, wb = cfg.risk_weight(sc.defects[0]), cfg.risk_weight(sc.defects[1])
    assert breakdown.exposure == (wa + wb) * 48
    assert breakdown.critical_penalty == cfg.critical_penalty  # only "a" is severity 5
    plan = [Assignment(defect_id="a", crew_id="c", start=8, end=10)]
    assert evaluate(sc, cfg, plan).exposure == wa * 10 + wb * 48


def test_validate_catches_violations():
    sc = _two_defects()
    bad = [
        Assignment(defect_id="a", crew_id="c", start=8, end=10),
        Assignment(defect_id="b", crew_id="c", start=9, end=11),  # overlap and outside window
    ]
    errors = validate(sc, bad)
    assert any("overlap" in e for e in errors)
    assert any("outside every window" in e for e in errors)
    good = [Assignment(defect_id="a", crew_id="c", start=8, end=10),
            Assignment(defect_id="b", crew_id="c", start=32, end=34)]
    assert validate(sc, good) == []


def test_moved_jobs_and_utilisation():
    prev = [Assignment(defect_id="a", crew_id="c", start=8, end=10),
            Assignment(defect_id="b", crew_id="c", start=32, end=34)]
    new = [Assignment(defect_id="a", crew_id="c", start=8, end=10),
           Assignment(defect_id="b", crew_id="c", start=34, end=36)]
    assert moved_jobs(prev, new, now=9) == ["b"]  # "a" already started, not counted
    util = crew_utilisation(_two_defects(), new)
    assert util["c"] == 4 / 16
