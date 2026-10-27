import pytest

from backend.planner.baseline import priority_sort
from backend.planner.compare import compare
from backend.planner.generator import generate_scenario
from backend.planner.metrics import validate
from backend.planner.models import Crew, Defect, PlannerConfig, Scenario

SEEDS = [0, 1, 2, 3, 4, 5]
CONFIG = PlannerConfig(time_limit_s=5)


def test_baseline_is_valid_and_orders_by_severity():
    sc = Scenario(
        name="b", horizon_days=1,
        defects=[Defect(id="s2", asset="A", severity=2, failure_risk=0.9, repair_hours=4, skill="x"),
                 Defect(id="s5", asset="B", severity=5, failure_risk=0.1, repair_hours=4, skill="x")],
        crews=[Crew(id="c", skills=["x"])],
    )
    plan = priority_sort(sc)
    assert plan.assignment("s5").start == 8 and plan.assignment("s2").start == 12
    assert plan.stats.status == "HEURISTIC" and not plan.stats.is_optimal
    assert validate(sc, plan.assignments) == []


@pytest.mark.parametrize("seed", SEEDS)
def test_cpsat_never_worse_than_baseline(seed):
    sc = generate_scenario(seed, n_defects=30)
    result = compare(sc, CONFIG)
    assert result.cpsat.objective <= result.baseline.objective
    assert result.cpsat.critical_unscheduled <= result.baseline.critical_unscheduled or \
        result.cpsat.objective < result.baseline.objective
    assert 0.0 <= result.cpsat.mean_crew_utilisation <= 1.0
    assert result.cpsat.solve_time_s > 0 and result.baseline.solve_time_s > 0
