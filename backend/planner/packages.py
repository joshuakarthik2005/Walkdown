"""Work packages: group register defects that one crew would repair in one visit.

A walkdown of one asset often finds several nearby corrosion spots. Planning each as its own job overstates the
work (each job pays its own setup: permit, access, scaffolding, surface preparation) and makes the schedule
needlessly large. Defects are grouped into one package when they are:

- on the same asset, and within ``max_frame_gap`` of each other along the walkdown (frame index; the frame
  distance is the stand-in for physical distance, since the camera moves along the asset);
- compatible to work on together: same shutdown need, and permits that one permit covers (no permit, or the
  same permit; a package without a permit can take a member that needs one);
- doable by one crew: the union of skills must be held by at least one crew in the scenario, otherwise the
  defect starts a new package;
- not severe: defects at severity >= ``single_from_severity`` (default 4) are never bundled. A package finishes
  all its members at its end, so bundling could only make a severe repair finish later.

A package is one planner job:
- repair hours = sum of members minus ``setup_saving_hours`` per extra member (never less than the longest member);
- severity = max; failure risk = 1 - prod(1 - r_i) (shown: the package fails if any member fails);
- exposure weight = the sum of the members' own weights, so the planner objective is exactly the per-defect exposure
  (every member counts as unrepaired until its package ends) and packaged and unpackaged plans compare directly;
- skill = the most severe member's skill, extra_skills = the rest; permit = the shared permit;
- found_at = earliest. Packages are capped at ``max_package_hours`` (default 24 h, three shifts), and shutdown-only
  packages at ``max_shutdown_package_hours`` (default 8 h, one shift) so they still fit inside a shutdown window.

Single-defect packages keep the defect's own id, so a plan without groupings looks exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from .models import Assignment, Crew, Defect, PlannerConfig


class PackageConfig(BaseModel):
    """How register defects are grouped into work packages."""

    enabled: bool = True
    max_frame_gap: int | None = Field(default=None, description="Max frame-index gap to the nearest member; "
                                                                "None = anywhere on the same asset.")
    setup_saving_hours: int = Field(default=1, ge=0, description="Hours saved per extra member (shared setup).")
    max_package_hours: int = Field(default=24, ge=1, description="Cap on a package's repair hours (3 shifts).")
    max_shutdown_package_hours: int = Field(default=8, ge=1, description="Cap for shutdown-only packages, which "
                                            "must fit inside a shutdown window (one shift).")
    single_from_severity: int = Field(default=4, ge=1, le=6, description="Defects at or above this severity are "
                                      "never bundled: a package could only finish them later.")


@dataclass
class _Open:
    members: list[tuple[Defect, list[int]]]

    @property
    def hours(self) -> int:
        return sum(d.repair_hours for d, _ in self.members)

    @property
    def skills(self) -> set[str]:
        return {s for d, _ in self.members for s in d.skills}

    @property
    def permit(self) -> str | None:
        return next((d.permit for d, _ in self.members if d.permit), None)

    @property
    def frames(self) -> list[int]:
        return [f for _, fs in self.members for f in fs]


def _package_hours(defects: list[Defect], saving: int) -> int:
    total = sum(d.repair_hours for d in defects) - saving * (len(defects) - 1)
    return max(total, max(d.repair_hours for d in defects))


def _fits(pkg: _Open, d: Defect, frames: list[int], crews: list[Crew], cfg: PackageConfig) -> bool:
    first = pkg.members[0][0]
    if max(d.severity, first.severity) >= cfg.single_from_severity:
        return False
    if d.asset != first.asset or d.needs_shutdown != first.needs_shutdown:
        return False
    if d.permit and pkg.permit and d.permit != pkg.permit:
        return False
    cap = cfg.max_shutdown_package_hours if d.needs_shutdown else cfg.max_package_hours
    if _package_hours([m for m, _ in pkg.members] + [d], cfg.setup_saving_hours) > cap:
        return False
    if cfg.max_frame_gap is not None and frames and pkg.frames:
        if min(abs(a - b) for a in frames for b in pkg.frames) > cfg.max_frame_gap:
            return False
    skills = pkg.skills | d.skills
    return any(skills <= set(c.skills) for c in crews)


def build_packages(defects: list[Defect], frames: dict[str, list[int]], crews: list[Crew],
                   config: PackageConfig | None = None, *, planner: PlannerConfig | None = None,
                   prefix: str = "WP") -> list[Defect]:
    """Group walkdown defects into work-package jobs (most severe first, then by position along the walkdown)."""
    cfg = config or PackageConfig()
    planner = planner or PlannerConfig()
    if not cfg.enabled:
        return list(defects)
    order = sorted(defects, key=lambda d: (-d.severity, min(frames.get(d.id) or [0]), d.id))
    packages: list[_Open] = []
    for d in order:
        fs = frames.get(d.id, [])
        target = next((p for p in packages if _fits(p, d, fs, crews, cfg)), None)
        if target is None:
            packages.append(_Open([(d, fs)]))
        else:
            target.members.append((d, fs))
    out, k = [], 0
    for p in packages:
        ds = [d for d, _ in p.members]
        if len(ds) == 1:
            out.append(ds[0])
            continue
        k += 1
        lead = ds[0]  # most severe (sorted above)
        survive = 1.0
        for d in ds:
            survive *= 1.0 - d.failure_risk
        out.append(Defect(
            id=f"{prefix}{k}", asset=lead.asset, defect_type=lead.defect_type, severity=max(d.severity for d in ds),
            failure_risk=round(min(0.99, 1.0 - survive), 3), repair_hours=_package_hours(ds, cfg.setup_saving_hours),
            skill=lead.skill, extra_skills=sorted(p.skills - {lead.skill}), needs_shutdown=lead.needs_shutdown,
            permit=p.permit, found_at=min(d.found_at for d in ds), service=lead.service,
            members=sorted(d.id for d in ds), weight_override=sum(planner.risk_weight(d) for d in ds)))
    return out


def package_of(jobs: list[Defect]) -> dict[str, str]:
    """Register defect id -> planner job id (its own id when not grouped)."""
    out = {}
    for j in jobs:
        for m in j.members or [j.id]:
            out[m] = j.id
    return out


def unpack(jobs: list[Defect], assignments: list[Assignment]) -> list[Assignment]:
    """Per-defect assignments: every member of a package gets its package's crew, start and end."""
    by_id = {j.id: j for j in jobs}
    out = []
    for a in assignments:
        j = by_id.get(a.defect_id)
        for m in (j.members if j is not None and j.members else [a.defect_id]):
            out.append(a.model_copy(update={"defect_id": m}))
    return out


def setup_hours_saved(jobs: list[Defect], originals: list[Defect]) -> int:
    """Repair hours saved by packaging: member hours minus package hours."""
    hours = {d.id: d.repair_hours for d in originals}
    return sum(sum(hours[m] for m in j.members) - j.repair_hours for j in jobs if j.members)
