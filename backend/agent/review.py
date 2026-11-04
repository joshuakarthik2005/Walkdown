"""Human review of the register and the plan: decision support, a person decides.

Every register entry carries a reviewer decision: "pending" (default), "approved", "rejected" or "reinspect"
(needs re-inspection). Entries the senior review disputed start as "reinspect" and stay visible. The plan can be
approved only when no severity >= 4 entry is still pending; a replan or a later decision withdraws the approval,
because the plan it approved has changed.

Rejected entries are excluded from the next replan by filtering the planner's input (the scenario, the previous
plan and their work packages); the solver itself is unchanged.

Decisions live on the agent session, so they are per run (in memory on the demo server) and work the same for
live runs, cached samples and finished examples.
"""

from __future__ import annotations

from datetime import datetime, timezone

import json
from dataclasses import replace

from backend.planner.models import Plan, PlannerConfig
from backend.planner.packages import PackageConfig, shrink_package

DECISIONS = ("pending", "approved", "rejected", "reinspect")
LABEL = {"pending": "Pending review", "approved": "Approved", "rejected": "Rejected",
         "reinspect": "Needs re-inspection"}
APPROVAL_SEVERITY = 4  # the plan can be approved only when no entry at or above this severity is pending
SOURCES = ("verifier", "second opinion", "own value")  # where an approved entry's reviewer severity came from


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _state(s) -> dict:
    """Review state on the session; created on first use (also for sessions pickled before reviews existed)."""
    st = s.__dict__.get("review_state")
    if st is None:
        st = s.__dict__["review_state"] = dict(decisions={}, plan_approval=None, excluded=[])
    st.setdefault("applied_severity", {})  # defect id -> reviewer severity already fed to the planner
    return st


def disputed(entry) -> bool:
    """The senior reviewer disagreed with the first pass on this entry (kept, flagged for a person)."""
    return any("senior_disputed" in d.flags for d in entry.detections)


def initial_decision(entry) -> str:
    return "reinspect" if disputed(entry) else "pending"


def decision_of(s, entry) -> dict:
    """{decision, label, at, reviewer_severity, severity_source}; at is None until a person decides. An approved entry
    carries the severity the reviewer chose and where it came from (verifier, second opinion or own value)."""
    d = _state(s)["decisions"].get(entry.defect_id)
    decision = d["decision"] if d else initial_decision(entry)
    return dict(decision=decision, label=LABEL[decision], at=d["at"] if d else None,
                reviewer_severity=(d or {}).get("severity"), severity_source=(d or {}).get("source"))


def effective_severity(s, entry) -> int:
    """The severity the plan uses: the reviewer's for an approved entry, else the grade's."""
    return decision_of(s, entry)["reviewer_severity"] or entry.grade.severity


def set_decision(s, defect_id: str, decision: str, severity: int | None = None, source: str | None = None) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    entry = next((e for e in s.register if e.defect_id == defect_id), None)
    if entry is None:
        raise KeyError(defect_id)
    if decision == "approved":
        severity = severity or entry.grade.severity
        if not 1 <= severity <= 5:
            raise ValueError("severity must be 1-5")
        source = source or ("verifier" if severity == entry.grade.severity else "own value")
        if source not in SOURCES:
            raise ValueError(f"severity source must be one of {', '.join(SOURCES)}")
    else:
        severity = source = None
    st = _state(s)
    st["decisions"][defect_id] = dict(decision=decision, at=_now(), severity=severity, source=source)
    st["plan_approval"] = None  # the reviewed register changed: the plan needs approving again
    return decision_of(s, entry)


def rejected_ids(s) -> set[str]:
    return {e.defect_id for e in s.register if decision_of(s, e)["decision"] == "rejected"}


def excluded_ids(s) -> set[str]:
    """Rejected entries already taken out of the current plan (by a replan)."""
    return set(_state(s)["excluded"])


def blocking_entries(s) -> list[str]:
    """Severity >= 4 entries still pending: they block plan approval."""
    return [e.defect_id for e in s.register
            if effective_severity(s, e) >= APPROVAL_SEVERITY and decision_of(s, e)["decision"] == "pending"]


def approve_plan(s) -> dict:
    if s.plan is None:
        raise ValueError("No plan yet: run the agent first.")
    blocking = blocking_entries(s)
    if blocking:
        raise ValueError(f"Review the severity 4-5 entries first: {', '.join(blocking)} still pending.")
    _state(s)["plan_approval"] = dict(at=_now())
    return review_summary(s)


def withdraw_plan_approval(s) -> None:
    _state(s)["plan_approval"] = None


def review_summary(s) -> dict:
    counts = {k: 0 for k in DECISIONS}
    for e in s.register:
        counts[decision_of(s, e)["decision"]] += 1
    rejected, excluded = rejected_ids(s), excluded_ids(s)
    return dict(counts=counts, blocking=blocking_entries(s), plan_approval=_state(s)["plan_approval"],
                rejected_excluded=sorted(rejected & excluded), rejected_pending_replan=sorted(rejected - excluded))


def exclude_rejected(s, planner: PlannerConfig, packages: PackageConfig) -> list[str]:
    """Take newly rejected entries out of every plan variant before a replan; returns the ids taken out.

    Per variant: a job whose members are all rejected is removed from the scenario and from the previous plan
    (so it is not counted as a moved job); a work package that loses some members is rebuilt from the rest
    (same id, fewer hours and less risk).
    """
    drop = rejected_ids(s) - excluded_ids(s)
    resev = _severity_updates(s) if s.variants else {}
    if (not drop and not resev) or not s.variants:
        return []
    singles = {d.id: d for d in s.variants.get("individual", {}).get("jobs", [])}
    singles.update(resev)  # approved entries at the reviewer's severity
    for name, v in list(s.variants.items()):
        jobs, removed, replaced = [], set(), {}
        for j in v["jobs"]:
            members = j.members or [j.id]
            keep = [m for m in members if m not in drop]
            if not keep:
                removed.add(j.id)
            elif not j.members and j.id in resev:
                replaced[j.id] = resev[j.id]
                jobs.append(resev[j.id])
            elif len(keep) == len(members) and not set(keep) & set(resev):
                jobs.append(j)
            else:
                nj = shrink_package(j, [singles[m] for m in keep], packages, planner)
                replaced[j.id] = nj
                jobs.append(nj)
        sc = v["scenario"]
        removed |= drop & {d.id for d in sc.defects}  # a variant kept without its job list (single plan)
        defects = [replaced.get(d.id, d) for d in sc.defects if d.id not in removed]
        plan: Plan = v["plan"]
        prev = plan.model_copy(update={"assignments": [a for a in plan.assignments if a.defect_id not in removed]})
        s.variants[name] = dict(v, jobs=jobs, scenario=sc.model_copy(update={"defects": defects}), plan=prev)
    st = _state(s)
    st["excluded"] = sorted(excluded_ids(s) | drop)
    st["applied_severity"].update({k: d.severity for k, d in resev.items()})
    return sorted(drop)


def _severity_updates(s) -> dict:
    """Planner defects for approved entries whose reviewer severity is not in the plan yet (the rule-based mapping,
    backend.agent.register.to_planner_defect, with the reviewer's severity in place of the grade's)."""
    from backend.agent.register import to_planner_defect
    st, out = _state(s), {}
    singles = {d.id: d for d in s.variants.get("individual", {}).get("jobs", [])}
    for e in s.register:
        sev = decision_of(s, e)["reviewer_severity"]
        if sev is None or e.defect_id not in singles:
            continue
        if sev == st["applied_severity"].get(e.defect_id, e.grade.severity):
            continue
        g = e.grade.model_copy(update={"severity": sev})
        entry = replace(e, detections=[replace(d, grade=g) for d in e.detections])
        out[e.defect_id] = to_planner_defect(entry, found_at=singles[e.defect_id].found_at)
    return out


def opinions(s, entry) -> list[dict]:
    """The opinions behind an entry: the verifier's first pass and, when it was escalated, the second opinion.

    The second opinion's own grade is kept only when it changed or confirmed the grade. When it disputed a defect,
    Walkdown keeps the first-pass grade (fail-safe), so for the second opinion only "not a defect" is known."""
    det = next((d for d in entry.detections if d.senior), None)
    g = entry.grade

    def cues(gr) -> str:
        return "; ".join(gr.evidence.visual_cues[:2])

    if det is None:
        return [dict(source="verifier", model="Muse Spark", is_defect=True, severity=g.severity, evidence=cues(g))]
    sr = det.senior
    disputed_ = bool(sr["changed_decision"] and sr["first_is_defect"])
    first = None
    if not disputed_:  # the kept grade is the second opinion's; the first pass is in the clip's verdict cache
        try:
            from backend.agent.tools import _verdict_cache
            from backend.verify.schema import Grade
            path = _verdict_cache(s, det.candidate_id)
            if path.exists():
                fg = json.loads(path.read_text(encoding="utf-8")).get("grade")
                first = Grade.model_validate(fg) if fg else None
        except Exception:  # noqa: BLE001 - a missing cache only hides the first-pass evidence
            first = None
    verifier = dict(source="verifier", model="Muse Spark", is_defect=sr["first_is_defect"],
                    severity=sr["first_severity"],
                    evidence=cues(det.grade) if disputed_ else (cues(first) if first else "first-pass evidence not kept"))
    if disputed_:
        second = dict(source="second opinion", model="Muse Wonder", is_defect=False, severity=None,
                      evidence=f"judged not a defect (escalated for {sr['reason']}); its own grade is not kept")
    else:
        second = dict(source="second opinion", model="Muse Wonder", is_defect=det.grade.is_defect,
                      severity=det.grade.severity, evidence=cues(det.grade))
    return [verifier, second]
