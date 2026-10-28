"""Tiered verification: which grades escalate, and how the senior grade replaces the first pass."""

import numpy as np

from backend.verify import escalation
from backend.verify.schema import Grade
from backend.verify.verifier import Candidate, Verdict


def grade(is_defect=True, severity=2, confidence=0.9) -> Grade:
    return Grade.model_validate({
        "is_defect": is_defect, "defect_type": "corrosion" if is_defect else "none", "severity": severity,
        "confidence": confidence, "recommended_action": "monitor" if is_defect else "no_action",
        "evidence": {"visual_cues": ["orange scale"], "location": "pipe", "extent": "small", "mask_fit": "good"}})


def verdict(g: Grade | None, provider="meta") -> Verdict:
    return Verdict(candidate_id="c1", provider=provider, grade=g, flags=[], input_tokens=10, cached_tokens=0,
                   output_tokens=10, reasoning_tokens=0, usd=0.001, latency_s=1.0, attempts=1)


CAND = Candidate("c1", np.zeros((8, 8, 3), np.uint8), np.ones((8, 8), bool), (0, 0, 8, 8), 0.5)


def test_escalation_rules():
    assert escalation.escalation_reason(grade(severity=4)) == "severity 4"
    assert escalation.escalation_reason(grade(severity=5)) == "severity 5"
    assert escalation.escalation_reason(grade(confidence=0.55)) == "confidence 0.55"
    assert escalation.escalation_reason(grade(is_defect=False, severity=1, confidence=0.9)) is None
    assert escalation.escalation_reason(grade(severity=3, confidence=0.6)) is None
    assert escalation.escalation_reason(None) is None  # invalid replies go to human review, not senior review


def test_not_escalated_makes_no_call(monkeypatch):
    monkeypatch.setattr(escalation, "verify", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    first = verdict(grade(severity=2))
    final, review = escalation.senior_review(CAND, first)
    assert final is first and review is None


def test_senior_rejection_keeps_the_defect_for_human_review(monkeypatch):
    monkeypatch.setattr(escalation, "verify", lambda c, **k: verdict(grade(is_defect=False, severity=1), "wonder"))
    first = verdict(grade(severity=4))
    final, review = escalation.senior_review(CAND, first)
    assert final.grade.is_defect and final.grade.severity == 4 and "senior_disputed" in final.flags
    assert review.changed_decision and not review.changed_severity and review.first_severity == 4


def test_senior_acceptance_of_a_first_pass_rejection_is_final(monkeypatch):
    monkeypatch.setattr(escalation, "verify", lambda c, **k: verdict(grade(severity=3), "wonder"))
    final, review = escalation.senior_review(CAND, verdict(grade(is_defect=False, severity=1, confidence=0.4)))
    assert final.provider == "wonder" and final.grade.is_defect and "senior_changed_decision" in final.flags


def test_severity_change_and_invalid_senior_reply(monkeypatch):
    monkeypatch.setattr(escalation, "verify", lambda c, **k: verdict(grade(severity=3), "wonder"))
    final, review = escalation.senior_review(CAND, verdict(grade(severity=5)))
    assert review.changed_severity and not review.changed_decision and final.grade.severity == 3
    monkeypatch.setattr(escalation, "verify", lambda c, **k: verdict(None, "wonder"))
    final, review = escalation.senior_review(CAND, verdict(grade(confidence=0.4)))
    assert not review.valid and final.grade.confidence == 0.4 and "senior_review_failed" in final.flags
