"""Tiered verification: uncertain or severe first-pass grades get a senior review by Muse Wonder.

A first-pass grade is escalated when it accepts a defect at severity >= 4 (where a wrong call matters most) or
when its confidence is below 0.6. Muse Wonder (``muse-wonder-1.0``) sees the same images, prompt and schema; its
grade becomes the final one, with one fail-safe exception: when Muse Wonder rejects a defect the first pass
accepted, the defect is NOT dropped. The first-pass grade is kept and the entry is flagged ``senior_disputed`` for
human review (on the test split the senior reviewer rejected 7.7% of escalated annotated-corrosion candidates;
benchmark/RESULTS.md section 5). The first-pass grade is kept in ``SeniorReview`` so the register and the agent
trail can show what changed. Senior review runs in Cloud mode only (Muse Wonder is a hosted model).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from backend.clients.cost import CostLedger
from backend.verify.schema import Grade
from backend.verify.verifier import WONDER_MODEL, Candidate, Verdict, verify

ESCALATE_SEVERITY = 4
ESCALATE_CONFIDENCE = 0.6


@dataclass
class SeniorReview:
    """What the senior reviewer changed relative to the first pass."""

    model: str
    first_is_defect: bool
    first_severity: int
    first_confidence: float
    changed_decision: bool
    changed_severity: bool
    reason: str  # why it was escalated
    usd: float
    latency_s: float
    valid: bool  # False: the senior reply was invalid and the first-pass grade was kept

    def to_dict(self) -> dict:
        return asdict(self)


def escalation_reason(grade: Grade | None) -> str | None:
    """Why a first-pass grade needs senior review, or None. Invalid replies go to human review instead."""
    if grade is None:
        return None
    if grade.is_defect and grade.severity >= ESCALATE_SEVERITY:
        return f"severity {grade.severity}"
    if grade.confidence < ESCALATE_CONFIDENCE:
        return f"confidence {grade.confidence:.2f}"
    return None


def senior_review(c: Candidate, first: Verdict, *, effort: str = "low", ledger: CostLedger | None = None,
                  job: str = "senior-review") -> tuple[Verdict, SeniorReview | None]:
    """Escalate if needed; returns the final verdict and the review record (None when not escalated)."""
    reason = escalation_reason(first.grade)
    if reason is None:
        return first, None
    senior = verify(c, provider="wonder", reasoning_effort=effort, ledger=ledger, job=job)
    g0, g1 = first.grade, senior.grade
    review = SeniorReview(model=WONDER_MODEL, first_is_defect=g0.is_defect, first_severity=g0.severity,
                          first_confidence=g0.confidence,
                          changed_decision=bool(g1 and g1.is_defect != g0.is_defect),
                          changed_severity=bool(g1 and g1.is_defect and g0.is_defect and g1.severity != g0.severity),
                          reason=reason, usd=senior.usd or 0.0, latency_s=senior.latency_s, valid=g1 is not None)
    if g1 is None:
        return Verdict(**{**asdict(first), "grade": g0, "flags": first.flags + ["senior_review_failed"]}), review
    if g0.is_defect and not g1.is_defect:  # fail safe: a disputed defect goes to a human, never silently away
        return Verdict(**{**asdict(first), "grade": g0, "flags": first.flags + ["senior_disputed"]}), review
    flags = list(senior.flags) + (["senior_changed_decision"] if review.changed_decision else [])
    return Verdict(**{**asdict(senior), "grade": g1, "flags": flags}), review
