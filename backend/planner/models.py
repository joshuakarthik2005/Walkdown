"""Data model for the Walkdown maintenance planner.

Time is discretised into 1-hour slots. Hour 0 is midnight at the start of
day 0 of the plan; the horizon is ``horizon_days * 24`` hours. All times
(shift starts, windows, unavailability, assignments) are integer hours on
that grid. See docs/DECISIONS.md for the rationale.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeRange(BaseModel):
    """Half-open range of hours ``[start, end)``."""

    model_config = ConfigDict(frozen=True)

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be after start ({self.start})")
        return self

    def overlaps(self, start: int, end: int) -> bool:
        """True if ``[start, end)`` intersects this range."""
        return start < self.end and self.start < end


class ServiceType(str, Enum):
    """What the line or vessel carries; drives the consequence of a failure."""

    LPG = "lpg"
    CRUDE = "crude"
    HYDROGEN = "hydrogen"
    HYDROCARBON_VAPOUR = "hydrocarbon_vapour"
    CHEMICAL = "chemical"
    STEAM = "steam"
    COOLING_WATER = "cooling_water"
    FIRE_WATER = "fire_water"
    AIR_NITROGEN = "air_nitrogen"


# Default consequence factors. These are ASSUMPTIONS for the demo (relative severity of a loss of
# containment by service, chosen by judgement), not industry figures; see docs/DECISIONS.md.
DEFAULT_CONSEQUENCE = {
    ServiceType.HYDROGEN: 3.0,
    ServiceType.LPG: 3.0,
    ServiceType.HYDROCARBON_VAPOUR: 2.5,
    ServiceType.CRUDE: 2.0,
    ServiceType.CHEMICAL: 2.0,
    ServiceType.STEAM: 1.5,
    ServiceType.FIRE_WATER: 1.5,
    ServiceType.COOLING_WATER: 1.0,
    ServiceType.AIR_NITROGEN: 0.8,
}


class Defect(BaseModel):
    """A verified defect that needs a repair job."""

    id: str
    asset: str
    defect_type: str = "corrosion"
    severity: int = Field(ge=1, le=5)
    failure_risk: float = Field(ge=0.0, le=1.0)
    repair_hours: int = Field(ge=1)
    skill: str
    needs_shutdown: bool = False
    permit: str | None = None
    found_at: int = Field(default=0, ge=0, description="Hour the defect was found; exposure is counted from here.")
    service: ServiceType | None = Field(default=None, description="Line service; None means consequence factor 1.")


class Crew(BaseModel):
    """A maintenance crew working one shift per work day."""

    id: str
    name: str = ""
    skills: list[str]
    shift_start: int = Field(default=8, ge=0, le=23)
    shift_hours: int = Field(default=8, ge=1, le=24)
    work_days: list[int] | None = Field(default=None, description="Day indices worked; None means every day.")
    unavailable: list[TimeRange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shift_within_day(self) -> "Crew":
        if self.shift_start + self.shift_hours > 24:
            raise ValueError(f"crew {self.id}: shifts crossing midnight are not supported")
        return self


class ShutdownWindow(BaseModel):
    """A plant shutdown during which shutdown-only jobs may run."""

    id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "ShutdownWindow":
        if self.end <= self.start:
            raise ValueError(f"window {self.id}: end must be after start")
        return self


class PermitType(BaseModel):
    """A work permit class with a lead time and an optional concurrency cap."""

    id: str
    lead_hours: int = Field(default=0, ge=0)
    max_concurrent: int | None = Field(default=None, ge=1)


class Scenario(BaseModel):
    """Everything the planner needs for one plan."""

    name: str
    horizon_days: int = Field(default=14, ge=1)
    defects: list[Defect]
    crews: list[Crew]
    windows: list[ShutdownWindow] = Field(default_factory=list)
    permits: list[PermitType] = Field(default_factory=list)

    @property
    def horizon_hours(self) -> int:
        """Length of the planning horizon in 1-hour slots."""
        return self.horizon_days * 24

    def defect(self, defect_id: str) -> Defect:
        """Look up a defect by id."""
        return next(d for d in self.defects if d.id == defect_id)

    def crew(self, crew_id: str) -> Crew:
        """Look up a crew by id."""
        return next(c for c in self.crews if c.id == crew_id)

    def permit(self, permit_id: str | None) -> PermitType | None:
        """Look up a permit type by id; None for jobs without a permit."""
        if permit_id is None:
            return None
        return next(p for p in self.permits if p.id == permit_id)

    @model_validator(mode="after")
    def _consistent(self) -> "Scenario":
        for label, items in (("defect", self.defects), ("crew", self.crews),
                             ("window", self.windows), ("permit", self.permits)):
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} ids")
        permit_ids = {p.id for p in self.permits}
        for d in self.defects:
            if d.permit is not None and d.permit not in permit_ids:
                raise ValueError(f"defect {d.id}: unknown permit {d.permit!r}")
        return self


class PlannerConfig(BaseModel):
    """All objective weights and solver settings in one place."""

    severity_weight: dict[int, float] = Field(default_factory=lambda: {1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0, 5: 16.0})
    risk_scale: int = Field(default=100, ge=1, description="Scales failure_risk x severity_weight to an integer weight.")
    consequence_factor: dict[ServiceType, float] = Field(default_factory=lambda: dict(DEFAULT_CONSEQUENCE),
                                                          description="Per-service consequence multiplier (assumptions).")
    critical_severity: int = Field(default=5, ge=1, le=5)
    critical_penalty: int = Field(default=1_000_000, ge=0, description="Added per unscheduled critical defect.")
    high_severity: int = Field(default=4, ge=1, le=5, description="Severity from which a non-critical defect is 'high'.")
    high_penalty: int = Field(default=100_000, ge=0, description="Added per unscheduled high-priority defect.")
    move_penalty: int = Field(default=200, ge=0, description="Replanning: cost per already-planned job that moves.")
    lexicographic_replan: bool = Field(default=True, description="Replan in two stages: risk first, then stability.")
    replan_epsilon: float = Field(default=0.02, ge=0, description="Stage 2 may worsen stage-1 risk by at most this share.")
    stage1_time_share: float = Field(default=0.6, gt=0, lt=1, description="Share of the time limit given to stage 1.")
    move_job_weight: int = Field(default=24, ge=0, description="Stage 2: cost of one moved job, in displaced hours.")
    time_limit_s: float = Field(default=10.0, gt=0)
    num_workers: int = Field(default_factory=lambda: os.cpu_count() or 8, ge=1, description="Default: all cores.")
    random_seed: int = 0
    probing_level: int = Field(default=0, ge=0, le=2, description="CP-SAT presolve probing; 0 measured best here.")

    def likelihood(self, defect: Defect) -> float:
        """Severity-based likelihood term: failure_risk x severity weight."""
        return defect.failure_risk * self.severity_weight[defect.severity]

    def consequence(self, defect: Defect) -> float:
        """Consequence factor of the line's service (1.0 when unknown)."""
        return self.consequence_factor.get(defect.service, 1.0) if defect.service else 1.0

    def risk_weight(self, defect: Defect) -> int:
        """Integer exposure weight per hour unrepaired: risk_scale x likelihood x consequence."""
        return round(self.risk_scale * self.likelihood(defect) * self.consequence(defect))

    def is_critical(self, defect: Defect) -> bool:
        """True if the defect is at or above the critical severity."""
        return defect.severity >= self.critical_severity

    def is_high(self, defect: Defect) -> bool:
        """True if the defect is high priority but below critical."""
        return self.high_severity <= defect.severity < self.critical_severity

    def unscheduled_penalty(self, defect: Defect) -> int:
        """Penalty added if the defect is left unscheduled (two-tier: critical, high)."""
        if self.is_critical(defect):
            return self.critical_penalty
        if self.is_high(defect):
            return self.high_penalty
        return 0


# ---- Plan output -----------------------------------------------------------

class Assignment(BaseModel):
    """One repair job placed on a crew. ``end`` is wall-clock: work pauses off-shift."""

    defect_id: str
    crew_id: str
    start: int
    end: int


class SolveStats(BaseModel):
    """Solver outcome. ``status`` is the solver's own word; FEASIBLE is never OPTIMAL."""

    solver: Literal["cp-sat", "priority-sort"]
    status: str
    objective: float | None = None
    best_bound: float | None = None
    gap: float | None = None
    wall_time_s: float = 0.0
    fallback: str | None = Field(default=None, description="Set when the solver found nothing and the warm start was returned.")
    stages: list[dict] = Field(default_factory=list, description="Per-stage results for the two-stage replan.")

    @property
    def is_optimal(self) -> bool:
        """True only when the solver proved optimality."""
        return self.status == "OPTIMAL"


class ObjectiveBreakdown(BaseModel):
    """Objective terms, evaluated identically for every solver."""

    exposure: int
    critical_penalty: int
    high_penalty: int = 0
    move_penalty: int

    @property
    def total(self) -> int:
        """Sum of all terms; equals the CP-SAT objective."""
        return self.exposure + self.critical_penalty + self.high_penalty + self.move_penalty


class ReasonCode(str, Enum):
    """Why a job sits where it does, or why it was not scheduled."""

    ON_EARLIEST_POSSIBLE = "on_earliest_possible"
    PERMIT_LEAD_TIME = "permit_lead_time"
    OUTSIDE_SHIFT = "outside_shift"
    WAITING_FOR_SHUTDOWN_WINDOW = "waiting_for_shutdown_window"
    CREW_UNAVAILABLE = "crew_unavailable"
    CREW_CAPACITY = "crew_capacity"
    PERMIT_CONCURRENCY = "permit_concurrency"
    DEFERRED_BY_OPTIMISER = "deferred_by_optimiser"
    WORK_IN_PROGRESS = "work_in_progress"
    NO_SKILLED_CREW = "no_skilled_crew"
    DOES_NOT_FIT_IN_HORIZON = "does_not_fit_in_horizon"
    PERMIT_NOT_READY_IN_HORIZON = "permit_not_ready_in_horizon"
    NO_SHUTDOWN_WINDOW_FITS = "no_shutdown_window_fits"
    CROWDED_OUT = "crowded_out"


class Reason(BaseModel):
    """One structured reason. ``delay_hours`` is how much later it pushed the job."""

    code: ReasonCode
    delay_hours: int | None = None
    until_hour: int | None = None
    related_ids: list[str] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict, description="Extra structured facts, e.g. crew-hour capacity.")


class DefectExplanation(BaseModel):
    """Structured explanation for one defect, for Muse Spark to narrate later."""

    defect_id: str
    status: Literal["scheduled", "unscheduled", "in_progress", "completed"]
    crew_id: str | None = None
    start: int | None = None
    end: int | None = None
    release_hour: int
    earliest_feasible_start: int | None = None
    reasons: list[Reason]
    priority: dict = Field(default_factory=dict, description="Risk terms: service, likelihood, consequence, weight.")


class Plan(BaseModel):
    """A maintenance plan for one scenario at decision time ``now``."""

    scenario_name: str
    now: int = 0
    assignments: list[Assignment]
    unscheduled: list[str]
    stats: SolveStats
    breakdown: ObjectiveBreakdown
    critical_unscheduled: list[str] = Field(default_factory=list)
    high_unscheduled: list[str] = Field(default_factory=list)
    moved_jobs: list[str] = Field(default_factory=list)
    explanations: list[DefectExplanation] = Field(default_factory=list)

    def assignment(self, defect_id: str) -> Assignment | None:
        """The assignment for a defect, or None if unscheduled."""
        return next((a for a in self.assignments if a.defect_id == defect_id), None)


# ---- Replanning changes ----------------------------------------------------

class CrewUnavailable(BaseModel):
    """A crew cannot work during ``[start, end)``."""

    type: Literal["crew_unavailable"] = "crew_unavailable"
    crew_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class ShutdownWindowChanged(BaseModel):
    """A shutdown window moves to ``[new_start, new_end)``, or is cancelled if both are None."""

    type: Literal["shutdown_window_changed"] = "shutdown_window_changed"
    window_id: str
    new_start: int | None = None
    new_end: int | None = None


class NewDefect(BaseModel):
    """A defect found during the plan, e.g. by a follow-up walkdown."""

    type: Literal["new_defect"] = "new_defect"
    defect: Defect


Change = Annotated[Union[CrewUnavailable, ShutdownWindowChanged, NewDefect], Field(discriminator="type")]
