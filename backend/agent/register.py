"""Defect register: turn accepted verifier verdicts into planner defects.

One register entry per physical defect. Detections of the same region on
nearby frames of a clip are merged (box IoU >= ``MERGE_IOU`` within
``MERGE_FRAMES`` sampled frames), keeping the most severe grade.

Mapping to the planner's Defect fields is rule-based and documented in
docs/DECISIONS.md ("Register to planner mapping"); nothing is invented by
the language model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.planner.models import Defect
from backend.verify.schema import Action, DefectType, Grade

MERGE_IOU = 0.3
MERGE_FRAMES = 2

REPAIR_HOURS = {1: 2, 2: 3, 3: 6, 4: 10, 5: 12}
BASE_RISK = {1: 0.05, 2: 0.15, 3: 0.35, 4: 0.6, 5: 0.85}


@dataclass
class AssetInfo:
    """What the walkdown knows about the asset in a clip."""

    asset_id: str
    asset_type: str = "pipe"  # pipe, tank, valve, support, railing
    pressurised: bool = True
    location: str = ""


@dataclass
class Detection:
    """One accepted candidate on one frame."""

    candidate_id: str
    frame: int
    box: tuple[int, int, int, int]
    grade: Grade
    flags: list[str] = field(default_factory=list)


@dataclass
class RegisterEntry:
    """One defect in the register, possibly seen on several frames."""

    defect_id: str
    asset: AssetInfo
    detections: list[Detection]
    needs_review: bool

    @property
    def grade(self) -> Grade:
        """The most severe (then most confident) grade among the detections."""
        return max((d.grade for d in self.detections), key=lambda g: (g.severity, g.confidence))

    @property
    def frames(self) -> list[int]:
        return sorted({d.frame for d in self.detections})


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def build_register(detections: list[Detection], asset: AssetInfo, *, prefix: str = "W",
                   merge_across_frames: bool = True) -> list[RegisterEntry]:
    """Group accepted detections into register entries (one per physical defect)."""
    groups: list[list[Detection]] = []
    for det in sorted(detections, key=lambda d: (d.frame, d.candidate_id)):
        target = None
        if merge_across_frames:
            for g in groups:
                last = g[-1]
                if 0 < det.frame - last.frame <= MERGE_FRAMES and _iou(det.box, last.box) >= MERGE_IOU:
                    target = g
                    break
        if target is None:
            groups.append([det])
        else:
            target.append(det)
    return [RegisterEntry(defect_id=f"{prefix}{i + 1:02d}", asset=asset, detections=g,
                          needs_review=any(d.flags for d in g)) for i, g in enumerate(groups)]


def to_planner_defect(entry: RegisterEntry, *, found_at: int) -> Defect:
    """Rule-based mapping from a graded register entry to a schedulable planner defect."""
    g = entry.grade
    sev = g.severity
    if g.defect_type == DefectType.LEAK_STAIN:
        skill, permit = "mechanical", "cold_work"
    elif g.defect_type == DefectType.DAMAGED_INSULATION:
        skill, permit = "insulation", None
    elif sev >= 4 or g.recommended_action in (Action.REPAIR, Action.REPLACE):
        skill, permit = "welding", "hot_work"
    else:
        skill, permit = "coating", None
    if entry.asset.asset_type == "tank" and sev >= 4:
        permit = "confined_space"
    needs_shutdown = (sev >= 4 and entry.asset.pressurised) or g.defect_type == DefectType.LEAK_STAIN
    risk = round(min(0.95, BASE_RISK[sev] * (0.5 + 0.5 * g.confidence)), 2)
    return Defect(id=entry.defect_id, asset=entry.asset.asset_id, defect_type=g.defect_type.value, severity=sev,
                  failure_risk=risk, repair_hours=REPAIR_HOURS[sev], skill=skill, needs_shutdown=needs_shutdown,
                  permit=permit, found_at=found_at)
