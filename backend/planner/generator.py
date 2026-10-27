"""Seeded synthetic scenario generator for tests, benchmarks and the demo.

Run ``python -m backend.planner.generator`` to regenerate the fixed demo
scenario JSON. The committed JSON is the source of truth for the demo; the
generator only makes it reproducible.
"""

from __future__ import annotations

import random
from pathlib import Path

from .models import Crew, Defect, PermitType, Scenario, ShutdownWindow

SKILLS = ["coating", "insulation", "mechanical", "welding"]

# defect type -> (skill, permit or None, shutdown probability)
DEFECT_PROFILES = {
    "corrosion": ("coating", None, 0.2),
    "rust": ("coating", None, 0.1),
    "leak_stain": ("mechanical", "cold_work", 0.5),
    "damaged_insulation": ("insulation", None, 0.1),
    "wall_loss": ("welding", "hot_work", 0.6),
}

ASSET_KINDS = ["PIPE-RACK", "TANK", "VALVE", "PUMP", "HEAT-EXCH", "FLARE-LINE"]

PERMITS = [
    PermitType(id="cold_work", lead_hours=4),
    PermitType(id="hot_work", lead_hours=24, max_concurrent=2),
    PermitType(id="confined_space", lead_hours=48, max_concurrent=1),
]

DEMO_PATH = Path(__file__).parent / "scenarios" / "demo_scenario.json"
DEMO_SEED = 13  # picked from seeds 0-19 for a clear demo story; benchmarks use all seeds


def generate_scenario(
    seed: int,
    *,
    n_defects: int = 25,
    n_crews: int = 4,
    n_windows: int = 2,
    horizon_days: int = 14,
    name: str | None = None,
    window_lengths: tuple[int, ...] = (24, 36, 48),
    shutdown_scale: float = 1.0,
    permits: list[PermitType] | None = None,
) -> Scenario:
    """Build a random but reproducible scenario. Every skill is covered by at least one crew.

    ``window_lengths``, ``shutdown_scale`` (multiplies each defect type's
    shutdown probability) and ``permits`` (replaces the default permit types)
    let the benchmark build loose and tight regimes. The defaults reproduce the
    original scenarios exactly: the random draw sequence does not change.
    """
    rng = random.Random(seed)
    assets = [f"{kind}-{rng.randint(100, 999)}" for kind in ASSET_KINDS for _ in range(2)]

    crews = []
    for i in range(n_crews):
        skills = {SKILLS[i % len(SKILLS)]}
        if rng.random() < 0.5:
            skills.add(rng.choice(SKILLS))
        crews.append(Crew(
            id=f"C{i + 1}",
            name=f"Crew {chr(ord('A') + i)}",
            skills=sorted(skills),
            shift_start=rng.choice([6, 7, 8]),
            shift_hours=8,
        ))

    windows = []
    day = rng.randint(2, 4)
    for i in range(n_windows):
        length = rng.choice(list(window_lengths))
        start = day * 24 + 6
        if start + length > horizon_days * 24:
            break
        windows.append(ShutdownWindow(id=f"SD{i + 1}", start=start, end=start + length))
        day += rng.randint(3, 6)

    defects = []
    for i in range(n_defects):
        dtype = rng.choice(list(DEFECT_PROFILES))
        skill, permit, p_shutdown = DEFECT_PROFILES[dtype]
        asset = rng.choice(assets)
        if asset.startswith("TANK") and dtype in ("wall_loss", "leak_stain"):
            permit = "confined_space"
        severity = rng.choices([1, 2, 3, 4, 5], weights=[2, 3, 4, 3, 2])[0]
        failure_risk = round(min(0.95, max(0.05, severity / 6 + rng.uniform(-0.1, 0.1))), 2)
        defects.append(Defect(
            id=f"D{i + 1:02d}",
            asset=asset,
            defect_type=dtype,
            severity=severity,
            failure_risk=failure_risk,
            repair_hours=rng.choice([2, 3, 4, 6, 8, 10, 12]),
            skill=skill,
            needs_shutdown=bool(windows) and rng.random() < min(1.0, p_shutdown * shutdown_scale),
            permit=permit,
        ))

    return Scenario(
        name=name or f"synthetic-{seed}",
        horizon_days=horizon_days,
        defects=defects,
        crews=crews,
        windows=windows,
        permits=list(permits if permits is not None else PERMITS),
    )


def save_scenario(scenario: Scenario, path: Path) -> None:
    """Write a scenario as pretty JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_scenario(path: Path = DEMO_PATH) -> Scenario:
    """Load a scenario JSON (the demo scenario by default)."""
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    demo = generate_scenario(DEMO_SEED, n_defects=25, n_crews=4, n_windows=2, name="demo")
    save_scenario(demo, DEMO_PATH)
    print(f"wrote {DEMO_PATH} ({len(demo.defects)} defects, {len(demo.crews)} crews, {len(demo.windows)} windows)")
