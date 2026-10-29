"""Detection sensitivity: measured verifier operating points the user can choose between.

In inspection a missed defect is the dangerous error and every flag is reviewed by a person, so the default
favours recall. "Balanced" trades a few points of recall for about half the false alarms. Every figure is
measured (benchmark/RESULTS.md sections 8, 9 and 11) and shown in the UI with its sample size and 95% CI.

- recall: the builder's blind audits (113 real-rust candidates: 100 text-prompt + 50 box-only, unsure excluded).
- false alarms: share of the 191 real clean-pipe images (public negatives) with at least one accepted candidate,
  end to end (text + boxes + verifier).
"""

from __future__ import annotations

from typing import Literal

Sensitivity = Literal["high_recall", "balanced"]
DEFAULT: Sensitivity = "high_recall"

# prompt version of the hosted verifier per setting (backend/verify/verifier.py PROMPTS)
PROMPT_VERSION: dict[str, str] = {"high_recall": "v1", "balanced": "v2"}

OPERATING_POINTS = {
    "high_recall": dict(
        label="High recall", mode="cloud", default=True,
        verifier="Muse Spark (hosted), minimal effort, standard prompt",
        recall=dict(value=0.973, k=110, n=113, ci=[0.925, 0.991]),
        false_alarm_images=dict(value=0.120, k=23, n=191, ci=[0.082, 0.174]),
        note="Misses the fewest real defects; about 1 clean image in 8 gets a flag to review."),
    "balanced": dict(
        label="Balanced", mode="cloud", default=False,
        verifier="Muse Spark (hosted), minimal effort, look-alike checklist prompt (v2)",
        recall=dict(value=0.938, k=106, n=113, ci=[0.878, 0.970]),
        false_alarm_images=dict(value=0.068, k=13, n=191, ci=[0.040, 0.113]),
        note="About half the false alarms of High recall, at about 3.5 points less recall."),
    "on_prem": dict(
        label="On-prem (open weights)", mode="on-prem", default=False,
        verifier="Muse Spark Open (Baseten), standard prompt",
        recall=dict(value=0.956, k=108, n=113, ci=[0.901, 0.981]),
        false_alarm_images=dict(value=0.021, k=4, n=191, ci=[0.008, 0.053]),
        note="Fixed in On-prem mode. Recall was measured on the audited (hosted-SAM) candidates; false alarms on "
             "the full open-weights pipeline."),
}
