"""Planner benchmark: CP-SAT vs priority-sort, stratified by how constrained the plant is.

Two experiments, both on seeded synthetic scenarios:

1. Static planning, per regime: objective (exposure + penalties), exposure
   alone, unscheduled / critical / high counts, utilisation and solve time.
2. Replan stability: after the same change at hour 48, compare
   - CP-SAT replanning its own plan (started work fixed, moves penalised),
   - the baseline re-run from scratch on its own plan (started work fixed),
   - the baseline in "patch" mode (keep still-feasible jobs, then fill).

Run from the project root:
    .venv\\Scripts\\python.exe -m benchmark.planner_benchmark
Writes benchmark/results/planner_benchmark.json and benchmark/PLANNER_RESULTS.md.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from backend.planner.baseline import priority_sort
from backend.planner.compare import compare
from backend.planner.cpsat import solve
from backend.planner.generator import generate_scenario
from backend.planner.models import CrewUnavailable, Defect, NewDefect, PermitType, PlannerConfig, \
    ShutdownWindowChanged
from backend.planner.replan import apply_change

OUT_DIR = Path(__file__).parent
RESULTS_JSON = OUT_DIR / "results" / "planner_benchmark.json"
RESULTS_MD = OUT_DIR / "PLANNER_RESULTS.md"

REPLAN_AT = 48

REGIMES: dict[str, dict] = {
    # The population the demo seed was picked from (seeds 0-19, generator defaults).
    "default": dict(n_defects=25),
    "loose": dict(
        n_defects=15, window_lengths=(48, 72), shutdown_scale=0.5,
        permits=[PermitType(id="cold_work", lead_hours=4), PermitType(id="hot_work", lead_hours=24),
                 PermitType(id="confined_space", lead_hours=48)],
    ),
    "tight_capacity": dict(n_defects=45, n_crews=3),
    "tight_shutdown": dict(n_defects=25, window_lengths=(16, 24), shutdown_scale=2.0),
    "tight_permits": dict(
        n_defects=25,
        permits=[PermitType(id="cold_work", lead_hours=8, max_concurrent=1),
                 PermitType(id="hot_work", lead_hours=48, max_concurrent=1),
                 PermitType(id="confined_space", lead_hours=72, max_concurrent=1)],
    ),
}
STATIC_SEEDS = {"default": range(20)} | {r: range(10) for r in REGIMES if r != "default"}
REPLAN_SEEDS = {r: range(5) for r in REGIMES if r != "default"}


def _changes(scenario, cpsat_plan):
    """The same three changes for every method: busiest crew out 72 h, first window cancelled, new critical."""
    hours = {c.id: sum(a.end - a.start for a in cpsat_plan.assignments if a.crew_id == c.id) for c in scenario.crews}
    busiest = max(sorted(hours), key=lambda c: hours[c])
    out = [("crew_unavailable", CrewUnavailable(crew_id=busiest, start=REPLAN_AT, end=REPLAN_AT + 72))]
    if scenario.windows:
        out.append(("window_cancelled", ShutdownWindowChanged(window_id=scenario.windows[0].id)))
    out.append(("new_critical", NewDefect(defect=Defect(
        id="NEW", asset="PIPE-RACK-NEW", defect_type="corrosion", severity=5, failure_risk=0.9,
        repair_hours=6, skill="coating"))))
    return out


def run_static(config: PlannerConfig) -> list[dict]:
    rows = []
    for regime, seeds in STATIC_SEEDS.items():
        for seed in seeds:
            sc = generate_scenario(seed, name=f"{regime}-{seed}", **REGIMES[regime])
            r = compare(sc, config)
            rows.append(dict(regime=regime, seed=seed, n_defects=len(sc.defects),
                             cpsat=r.cpsat.model_dump(), baseline=r.baseline.model_dump()))
            print(f"static {regime:15} seed {seed:2} {r.cpsat.status:8} "
                  f"cpsat {r.cpsat.objective:>10} base {r.baseline.objective:>10}", flush=True)
    return rows


def run_replan(config: PlannerConfig) -> list[dict]:
    rows = []
    for regime, seeds in REPLAN_SEEDS.items():
        for seed in seeds:
            sc = generate_scenario(seed, name=f"{regime}-{seed}", **REGIMES[regime])
            cp_plan = solve(sc, config)
            base_plan = priority_sort(sc, config)
            for label, change in _changes(sc, cp_plan):
                changed = apply_change(sc, change, REPLAN_AT)
                cp_new = solve(changed, config, now=REPLAN_AT, previous=cp_plan)
                scratch = priority_sort(changed, config, now=REPLAN_AT, previous=base_plan)
                patch = priority_sort(changed, config, now=REPLAN_AT, previous=base_plan, keep_previous=True)
                row = dict(regime=regime, seed=seed, change=label)
                for name, plan in (("cpsat", cp_new), ("baseline_scratch", scratch), ("baseline_patch", patch)):
                    row[name] = dict(status=plan.stats.status, moved=len(plan.moved_jobs),
                                     objective=plan.breakdown.total, exposure=plan.breakdown.exposure,
                                     unscheduled=len(plan.unscheduled),
                                     critical_unscheduled=len(plan.critical_unscheduled))
                rows.append(row)
                print(f"replan {regime:15} seed {seed} {label:17} moved cpsat {row['cpsat']['moved']:2} "
                      f"scratch {row['baseline_scratch']['moved']:2} patch {row['baseline_patch']['moved']:2}",
                      flush=True)
    return rows


def _mmm(values: list[float], fmt: str = "{:.1f}") -> str:
    if not values:
        return "n/a"
    return f"{fmt.format(statistics.median(values))} ({fmt.format(min(values))} – {fmt.format(max(values))})"


def _pct(new: float, old: float) -> float:
    return 100.0 * (1 - new / old) if old else 0.0


def write_markdown(static: list[dict], replan: list[dict], config: PlannerConfig, elapsed_s: float) -> None:
    lines = [
        "# Planner benchmark: CP-SAT vs priority sort",
        "",
        "Generated by `python -m benchmark.planner_benchmark`. Raw rows: `results/planner_benchmark.json`.",
        f"CP-SAT time limit {config.time_limit_s:.0f} s, {config.num_workers} workers, warm-started from the "
        f"baseline. Total run time {elapsed_s / 60:.1f} min. Numbers are **median (min – max)** across seeds.",
        "",
        "The demo scenario (`default` regime, seed 13) was chosen from the 20 `default` seeds for illustration; "
        "it is not a typical result. Use the medians below.",
        "",
        "## Static planning",
        "",
        "Objective = risk-weighted exposure + critical/high unscheduled penalties. Improvement = "
        "1 − CP-SAT / baseline.",
        "",
        "| Regime | Seeds | Defects | Objective improvement % | Exposure reduction % | Unscheduled CP-SAT | "
        "Unscheduled baseline | Crit+high unscheduled CP-SAT / baseline | CP-SAT OPTIMAL | CP-SAT time s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for regime in STATIC_SEEDS:
        rs = [r for r in static if r["regime"] == regime]
        c = [r["cpsat"] for r in rs]
        b = [r["baseline"] for r in rs]
        lines.append(
            f"| {regime} | {len(rs)} | {rs[0]['n_defects']} "
            f"| {_mmm([_pct(x['objective'], y['objective']) for x, y in zip(c, b)])} "
            f"| {_mmm([_pct(x['exposure'], y['exposure']) for x, y in zip(c, b)])} "
            f"| {_mmm([x['unscheduled'] for x in c], '{:.0f}')} | {_mmm([y['unscheduled'] for y in b], '{:.0f}')} "
            f"| {sum(x['critical_unscheduled'] + x['high_unscheduled'] for x in c)} / "
            f"{sum(y['critical_unscheduled'] + y['high_unscheduled'] for y in b)} "
            f"| {sum(x['status'] == 'OPTIMAL' for x in c)}/{len(c)} "
            f"| {_mmm([x['solve_time_s'] for x in c])} |"
        )
    never_worse = all(r["cpsat"]["objective"] <= r["baseline"]["objective"] for r in static)
    lines += ["", f"CP-SAT objective ≤ baseline on every static run: **{never_worse}**.", "",
              "## Replan stability", "",
              f"Change applied at hour {REPLAN_AT}; work started before then is fixed for every method. "
              "Moved = previously planned (not started) jobs whose crew or start changed, or that were dropped. "
              "Each method replans its own original plan.", "",
              "| Regime | Change | Runs | Moved CP-SAT | Moved baseline scratch | Moved baseline patch | "
              "Objective vs scratch % | Objective vs patch % |",
              "|---|---|---|---|---|---|---|---|"]
    for regime in REPLAN_SEEDS:
        for change in ("crew_unavailable", "window_cancelled", "new_critical"):
            rs = [r for r in replan if r["regime"] == regime and r["change"] == change]
            if not rs:
                continue
            lines.append(
                f"| {regime} | {change} | {len(rs)} "
                f"| {_mmm([r['cpsat']['moved'] for r in rs], '{:.0f}')} "
                f"| {_mmm([r['baseline_scratch']['moved'] for r in rs], '{:.0f}')} "
                f"| {_mmm([r['baseline_patch']['moved'] for r in rs], '{:.0f}')} "
                f"| {_mmm([_pct(r['cpsat']['objective'], r['baseline_scratch']['objective']) for r in rs])} "
                f"| {_mmm([_pct(r['cpsat']['objective'], r['baseline_patch']['objective']) for r in rs])} |"
            )
    lines += ["", "Objective vs X % = 1 − CP-SAT objective / X objective after the change "
              "(includes CP-SAT's own move penalty; positive means CP-SAT is better).", ""]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    config = PlannerConfig()
    t0 = time.perf_counter()
    static = run_static(config)
    replan = run_replan(config)
    elapsed = time.perf_counter() - t0
    RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(dict(config=config.model_dump(), replan_at=REPLAN_AT, static=static,
                                            replan=replan, elapsed_s=elapsed), indent=1), encoding="utf-8")
    write_markdown(static, replan, config, elapsed)
    print(f"wrote {RESULTS_MD} and {RESULTS_JSON} in {elapsed / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
