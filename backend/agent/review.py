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

from backend.planner.models import Plan, PlannerConfig
from backend.planner.packages import PackageConfig, shrink_package

DECISIONS = ("pending", "approved", "rejected", "reinspect")
LABEL = {"pending": "Pending review", "approved": "Approved", "rejected": "Rejected",
         "reinspect": "Needs re-inspection"}
APPROVAL_SEVERITY = 4  # the plan can be approved only when no entry at or above this severity is pending


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _state(s) -> dict:
    """Review state on the session; created on first use (also for sessions pickled before reviews existed)."""
    st = s.__dict__.get("review_state")
    if st is None:
        st = s.__dict__["review_state"] = dict(decisions={}, plan_approval=None, excluded=[])
    return st


def disputed(entry) -> bool:
    """The senior reviewer disagreed with the first pass on this entry (kept, flagged for a person)."""
    return any("senior_disputed" in d.flags for d in entry.detections)


def initial_decision(entry) -> str:
    return "reinspect" if disputed(entry) else "pending"


def decision_of(s, entry) -> dict:
    """{decision, label, at}; at is None until a person decides."""
    d = _state(s)["decisions"].get(entry.defect_id)
    decision = d["decision"] if d else initial_decision(entry)
    return dict(decision=decision, label=LABEL[decision], at=d["at"] if d else None)


def set_decision(s, defect_id: str, decision: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    entry = next((e for e in s.register if e.defect_id == defect_id), None)
    if entry is None:
        raise KeyError(defect_id)
    st = _state(s)
    st["decisions"][defect_id] = dict(decision=decision, at=_now())
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
            if e.grade.severity >= APPROVAL_SEVERITY and decision_of(s, e)["decision"] == "pending"]


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
    if not drop or not s.variants:
        return []
    singles = {d.id: d for d in s.variants.get("individual", {}).get("jobs", [])}
    for name, v in list(s.variants.items()):
        jobs, removed, replaced = [], set(), {}
        for j in v["jobs"]:
            members = j.members or [j.id]
            keep = [m for m in members if m not in drop]
            if not keep:
                removed.add(j.id)
            elif len(keep) == len(members):
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
    _state(s)["excluded"] = sorted(excluded_ids(s) | drop)
    return sorted(drop)
