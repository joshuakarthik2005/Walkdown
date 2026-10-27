from backend.planner.compare import compare
from backend.planner.generator import DEMO_SEED, generate_scenario, load_scenario
from backend.planner.models import PlannerConfig


def test_demo_scenario_json_is_fixed_and_reproducible():
    demo = load_scenario()
    assert (len(demo.defects), len(demo.crews), len(demo.windows)) == (25, 4, 2)
    assert demo == generate_scenario(DEMO_SEED, n_defects=25, n_crews=4, n_windows=2, name="demo")


def test_demo_solves_to_optimal_and_beats_baseline():
    demo = load_scenario()
    result = compare(demo, PlannerConfig(time_limit_s=10))
    assert result.cpsat.status == "OPTIMAL"
    assert result.cpsat.objective < result.baseline.objective
    assert result.cpsat.critical_unscheduled == 0
