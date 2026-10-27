"""Run CP-SAT and the priority-sort baseline on the same scenario and compare."""

from __future__ import annotations

from pydantic import BaseModel

from .baseline import priority_sort
from .cpsat import solve
from .metrics import crew_utilisation
from .models import Plan, PlannerConfig, Scenario


class PlanSummary(BaseModel):
    """Headline numbers for one solver on one scenario."""

    solver: str
    status: str
    objective: int
    exposure: int
    critical_unscheduled: int
    unscheduled: int
    mean_crew_utilisation: float
    crew_utilisation: dict[str, float]
    solve_time_s: float
    gap: float | None


class Comparison(BaseModel):
    """CP-SAT vs baseline on one scenario."""

    scenario_name: str
    cpsat: PlanSummary
    baseline: PlanSummary

    @property
    def exposure_reduction(self) -> float:
        """Fraction of baseline risk-weighted exposure removed by CP-SAT."""
        return 1 - self.cpsat.exposure / self.baseline.exposure if self.baseline.exposure else 0.0


def summarise(scenario: Scenario, plan: Plan) -> PlanSummary:
    """Reduce a plan to the comparison metrics."""
    util = crew_utilisation(scenario, plan.assignments, now=plan.now)
    return PlanSummary(
        solver=plan.stats.solver,
        status=plan.stats.status,
        objective=plan.breakdown.total,
        exposure=plan.breakdown.exposure,
        critical_unscheduled=len(plan.critical_unscheduled),
        unscheduled=len(plan.unscheduled),
        mean_crew_utilisation=sum(util.values()) / len(util) if util else 0.0,
        crew_utilisation=util,
        solve_time_s=plan.stats.wall_time_s,
        gap=plan.stats.gap,
    )


def compare(scenario: Scenario, config: PlannerConfig | None = None) -> Comparison:
    """Solve with both methods; CP-SAT is warm-started from the baseline plan."""
    config = config or PlannerConfig()
    base = priority_sort(scenario, config)
    opt = solve(scenario, config, hint=base.assignments)
    return Comparison(scenario_name=scenario.name, cpsat=summarise(scenario, opt), baseline=summarise(scenario, base))


if __name__ == "__main__":
    from .generator import load_scenario

    demo = load_scenario()
    result = compare(demo)
    for s in (result.baseline, result.cpsat):
        print(f"{s.solver:14} status={s.status:9} objective={s.objective:>9} exposure={s.exposure:>9} "
              f"unscheduled={s.unscheduled} critical_unscheduled={s.critical_unscheduled} "
              f"utilisation={s.mean_crew_utilisation:.2f} time={s.solve_time_s:.2f}s")
    print(f"exposure reduction vs baseline: {100 * result.exposure_reduction:.1f}%")
