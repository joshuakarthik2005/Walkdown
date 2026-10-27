"""Verifier output schema and rule-based consistency checks."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DefectType(str, Enum):
    CORROSION = "corrosion"
    RUST_STAINING = "rust_staining"
    LEAK_STAIN = "leak_stain"
    DAMAGED_INSULATION = "damaged_insulation"
    COATING_DAMAGE = "coating_damage"
    NONE = "none"
    OTHER = "other"


class Action(str, Enum):
    NO_ACTION = "no_action"
    MONITOR = "monitor"
    CLEAN_AND_RECOAT = "clean_and_recoat"
    REPAIR = "repair"
    REPLACE = "replace"
    URGENT_INSPECTION = "urgent_inspection"


class MaskFit(str, Enum):
    GOOD = "good"
    PARTIAL = "partial"
    POOR = "poor"


class Evidence(BaseModel):
    """What the verifier based its decision on."""

    model_config = ConfigDict(extra="forbid")

    visual_cues: list[str] = Field(description="Short phrases: what is visible inside the outlined region.")
    location: str = Field(description="Where the region sits on the object (e.g. 'weld seam at pipe support').")
    extent: str = Field(description="How much of the visible surface is affected (e.g. 'small spot', 'most of the flange').")
    mask_fit: MaskFit = Field(description="How well the outline matches the actual defect.")


class Grade(BaseModel):
    """One verified, graded candidate."""

    model_config = ConfigDict(extra="forbid")

    is_defect: bool = Field(description="True only if the outlined region shows real corrosion or a related defect.")
    defect_type: DefectType
    severity: int = Field(ge=1, le=5, description="1 cosmetic ... 5 critical; use 1 when is_defect is false.")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Evidence
    recommended_action: Action


def grade_json_schema() -> dict:
    """Strict-mode JSON schema: every object closed, every key required, enums inline."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["is_defect", "defect_type", "severity", "confidence", "evidence", "recommended_action"],
        "properties": {
            "is_defect": {"type": "boolean"},
            "defect_type": {"type": "string", "enum": [e.value for e in DefectType]},
            "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "confidence": {"type": "number", "description": "0 to 1"},
            "evidence": {
                "type": "object",
                "additionalProperties": False,
                "required": ["visual_cues", "location", "extent", "mask_fit"],
                "properties": {
                    "visual_cues": {"type": "array", "items": {"type": "string"}},
                    "location": {"type": "string"},
                    "extent": {"type": "string"},
                    "mask_fit": {"type": "string", "enum": [e.value for e in MaskFit]},
                },
            },
            "recommended_action": {"type": "string", "enum": [e.value for e in Action]},
        },
    }


def consistency_flags(g: Grade) -> list[str]:
    """Contradictions that send a grade to human review instead of straight to the register."""
    flags = []
    if g.severity >= 5 and g.confidence < 0.5:
        flags.append("severity_5_low_confidence")
    if g.is_defect and g.defect_type == DefectType.NONE:
        flags.append("defect_without_type")
    if not g.is_defect and g.defect_type not in (DefectType.NONE, DefectType.OTHER):
        flags.append("rejected_but_typed")
    if not g.is_defect and g.severity >= 3:
        flags.append("rejected_but_severe")
    if g.is_defect and g.severity >= 4 and g.recommended_action in (Action.NO_ACTION, Action.MONITOR):
        flags.append("severe_but_no_action")
    if g.is_defect and g.evidence.mask_fit == MaskFit.POOR:
        flags.append("poor_mask_fit")
    return flags
