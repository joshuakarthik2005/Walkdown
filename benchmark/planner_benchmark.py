"""Planner benchmark: CP-SAT vs priority-sort, stratified by how constrained the plant is.

Two experiments, both on seeded synthetic scenarios:

1. Static planning, per regime: risk objective (exposure + penalties),
   exposure alone, unscheduled / critical / high counts, utilisation, status,
   gap and solve time.
2. Replan stability: after the same change at hour 48, compare
   - CP-SAT replanning its own plan (two-stage: risk, then churn; started work fixed),
   - the baseline re-run from scratch on its own plan (started work fixed),
   - the baseline in "patch" mode (keep still-feasible jobs, then fill).

Run one regime at a time from the project root (results are saved per regime),
then build the report:
    .venv\\Scripts\\python.exe -m benchmark.planner_benchmark run <regime>
    .venv\\Scripts\\python.exe -m benchmark.planner_benchmark report
Writes benchmark/results/planner_<regime>.json and benchmark/PLANNER_RESULTS.md.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from backend.planner.baseline import priority_sort
from backend.planner.compare import compare
from backend.planner.cpsat import solve
from backend.planner.generator import generate_scenario
from backend.planner.models import CrewUnavailable, Defect, NewDefect, PermitType, Plan, PlannerConfig, \
    ShutdownWindowChanged
from backend.planner.replan import apply_change

OUT_DIR = Path(__file__).parent
RESULTS_DIR = OUT_DIR / "results"
RESULTS_MD = OUT_DIR / "PLANNER_RESULTS.md"

REPLAN_AT = 48
CONFIG = PlannerConfig(num_workers=4)

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
CHANGES = ("crew_unavailable", "window_cancelled", "new_critical")


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


def _displaced_hours(previous: Plan, plan: Plan, horizon: int) -> int:
    """Total hours that previously planned, not-started jobs moved (dropped = to horizon end)."""
    now = {a.defect_id: a for a in plan.assignments}
    total = 0
    for p in previous.assignments:
        if p.start < REPLAN_AT:
            continue
        a = now.get(p.defect_id)
        total += abs(a.start - p.start) if a else horizon - p.start
    return total


def run_regime(regime: str) -> dict:
    """Run both experiments for one regime and save the rows."""
    t0 = time.perf_counter()
    static = []
    for seed in STATIC_SEEDS[regime]:
        sc = generate_scenario(seed, name=f"{regime}-{seed}", **REGIMES[regime])
        r = compare(sc, CONFIG)
        static.append(dict(seed=seed, n_defects=len(sc.defects), cpsat=r.cpsat.model_dump(),
                           baseline=r.baseline.model_dump()))
        print(f"static {regime} seed {seed:2} {r.cpsat.status:8} cpsat {r.cpsat.objective:>10} "
              f"base {r.baseline.objective:>10}", flush=True)

    replan = []
    for seed in REPLAN_SEEDS.get(regime, []):
        sc = generate_scenario(seed, name=f"{regime}-{seed}", **REGIMES[regime])
        cp_plan = solve(sc, CONFIG)
        base_plan = priority_sort(sc, CONFIG)
        for label, change in _changes(sc, cp_plan):
            changed = apply_change(sc, change, REPLAN_AT)
            methods = {
                "cpsat": (cp_plan, solve(changed, CONFIG, now=REPLAN_AT, previous=cp_plan)),
                "baseline_scratch": (base_plan, priority_sort(changed, CONFIG, now=REPLAN_AT, previous=base_plan)),
                "baseline_patch": (base_plan, priority_sort(changed, CONFIG, now=REPLAN_AT, previous=base_plan,
                                                            keep_previous=True)),
            }
            row = dict(seed=seed, change=label)
            for name, (prev, plan) in methods.items():
                row[name] = dict(
                    status=plan.stats.status, stages=[s["status"] for s in plan.stats.stages],
                    moved=len(plan.moved_jobs), displaced_hours=_displaced_hours(prev, plan, sc.horizon_hours),
                    risk=plan.breakdown.total - plan.breakdown.move_penalty, exposure=plan.breakdown.exposure,
                    unscheduled=len(plan.unscheduled), critical_unscheduled=len(plan.critical_unscheduled),
                    solve_time_s=plan.stats.wall_time_s,
                )
            replan.append(row)
            print(f"replan {regime} seed {seed} {label:17} moved cpsat {row['cpsat']['moved']:2} "
                  f"scratch {row['baseline_scratch']['moved']:2} patch {row['baseline_patch']['moved']:2}", flush=True)

    result = dict(regime=regime, config=CONFIG.model_dump(), replan_at=REPLAN_AT, static=static, replan=replan,
                  elapsed_s=time.perf_counter() - t0)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"planner_{regime}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"saved {regime} in {result['elapsed_s'] / 60:.1f} min")
    return result


def _mmm(values: list[float], fmt: str = "{:.1f}") -> str:
    if not values:
        return "n/a"
    return f"{fmt.format(statistics.median(values))} ({fmt.format(min(values))} – {fmt.format(max(values))})"


def _pct(new: float, old: float) -> float:
    return 100.0 * (1 - new / old) if old else 0.0


def write_report() -> None:
    """Build PLANNER_RESULTS.md from every saved regime file."""
    results = {}
    for regime in REGIMES:
        path = RESULTS_DIR / f"planner_{regime}.json"
        if path.exists():
            results[regime] = json.loads(path.read_text(encoding="utf-8"))
    total_min = sum(r["elapsed_s"] for r in results.values()) / 60
    lines = [
        "# Planner benchmark: CP-SAT vs priority sort",
        "",
        "Generated by `python -m benchmark.planner_benchmark report` from `results/planner_<regime>.json`.",
        f"CP-SAT: {CONFIG.time_limit_s:.0f} s limit, {CONFIG.num_workers} workers, warm-started from the baseline; "
        f"replans use the two-stage method (risk, then churn within {CONFIG.replan_epsilon:.0%}). "
        f"Total run time {total_min:.1f} min. Values are **median (min – max)** across seeds.",
        "",
        "The demo scenario (`default` regime, seed 13) was chosen from the 20 `default` seeds for illustration "
        "and is not a typical result. Read the medians.",
        "",
        "Risk objective = risk-weighted exposure + penalties for unscheduled critical (severity 5) and high "
        "(severity 4) defects. Improvement = 1 − CP-SAT / baseline.",
        "",
        "## Static planning",
        "",
        "| Regime | Seeds | Defects | Risk improvement % | Exposure reduction % | Unscheduled CP-SAT | "
        "Unscheduled baseline | Crit+high unscheduled CP-SAT / baseline | CP-SAT status | Gap % | CP-SAT time s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    all_static = []
    for regime, res in results.items():
        rows = res["static"]
        all_static += rows
        c = [r["cpsat"] for r in rows]
        b = [r["baseline"] for r in rows]
        status = ", ".join(f"{k} {v}" for k, v in sorted(Counter(x["status"] for x in c).items()))
        lines.append(
            f"| {regime} | {len(rows)} | {rows[0]['n_defects']} "
            f"| {_mmm([_pct(x['objective'], y['objective']) for x, y in zip(c, b)])} "
            f"| {_mmm([_pct(x['exposure'], y['exposure']) for x, y in zip(c, b)])} "
            f"| {_mmm([x['unscheduled'] for x in c], '{:.0f}')} | {_mmm([y['unscheduled'] for y in b], '{:.0f}')} "
            f"| {sum(x['critical_unscheduled'] + x['high_unscheduled'] for x in c)} / "
            f"{sum(y['critical_unscheduled'] + y['high_unscheduled'] for y in b)} "
            f"| {status} | {_mmm([100 * (x['gap'] or 0) for x in c])} "
            f"| {_mmm([x['solve_time_s'] for x in c])} |"
        )
    never_worse = all(r["cpsat"]["objective"] <= r["baseline"]["objective"] for r in all_static)
    lines += ["", f"CP-SAT risk objective ≤ baseline on every static run: **{never_worse}** "
              f"({len(all_static)} runs).", "",
              "## Replan stability", "",
              f"Change applied at hour {REPLAN_AT}; work started before then is fixed for every method, and each "
              "method replans its own original plan. Moved = previously planned, not-started jobs whose crew or "
              "start changed, or that were dropped. Displaced h = total hours those starts moved (dropped jobs "
              "count to the horizon end).", "",
              "| Regime | Change | Runs | Moved CP-SAT | Moved scratch | Moved patch | Displaced h CP-SAT | "
              "Displaced h patch | Risk vs scratch % | Risk vs patch % | CP-SAT status |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    more_than_patch = []
    for regime, res in results.items():
        for change in CHANGES:
            rows = [r for r in res["replan"] if r["change"] == change]
            if not rows:
                continue
            cp_moves = [r["cpsat"]["moved"] for r in rows]
            patch_moves = [r["baseline_patch"]["moved"] for r in rows]
            if statistics.median(cp_moves) > statistics.median(patch_moves):
                more_than_patch.append(f"{regime} / {change}")
            status = ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["cpsat"]["status"] for r in rows).items()))
            lines.append(
                f"| {regime} | {change} | {len(rows)} | {_mmm(cp_moves, '{:.0f}')} "
                f"| {_mmm([r['baseline_scratch']['moved'] for r in rows], '{:.0f}')} | {_mmm(patch_moves, '{:.0f}')} "
                f"| {_mmm([r['cpsat']['displaced_hours'] for r in rows], '{:.0f}')} "
                f"| {_mmm([r['baseline_patch']['displaced_hours'] for r in rows], '{:.0f}')} "
                f"| {_mmm([_pct(r['cpsat']['risk'], r['baseline_scratch']['risk']) for r in rows])} "
                f"| {_mmm([_pct(r['cpsat']['risk'], r['baseline_patch']['risk']) for r in rows])} | {status} |"
            )
    lines += ["", "Risk vs X % = 1 − CP-SAT risk / X risk after the change (positive = CP-SAT lower risk).", "",
              "### Where CP-SAT moves more jobs than the baseline patch (median)", ""]
    lines += [f"- {x}" for x in more_than_patch] or ["- none"]
    lines += ["", "CP-SAT trades extra moves for lower risk. The patch heuristic keeps every still-feasible job "
              "in place by construction, so it is the most stable but leaves more risk. Both are shown so the "
              "trade-off is visible.", ""]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {RESULTS_MD}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "run" and sys.argv[2] in REGIMES:
        run_regime(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "report":
        write_report()
    else:
        print(__doc__)
        print("regimes:", ", ".join(REGIMES))
        sys.exit(1)
