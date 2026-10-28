"""F5 inspector copilot: answers questions about a finished run's register and plan.

Same tool-calling loop as the walkdown agent, but with read-only tools over the session (register entries,
plan assignments, the planner's structured reasons, crews and windows). It cannot segment, verify, plan or
replan, and its prompt forbids facts that are not in a tool result. Works with either provider (Cloud:
hosted Muse Spark; On-prem: Muse Spark Open), because it follows the session's provider.
"""

from __future__ import annotations

from backend.agent.loop import WalkdownAgent
from backend.agent.tools import AgentSession, _fn, explain_plan

COPILOT_PROMPT = """You are the Walkdown inspector copilot. A walkdown has already been processed: there is a \
defect register and a maintenance plan. Answer the inspector's question using ONLY your tools, which read the \
register, the plan, the planner's structured reasons and the crews and shutdown windows. Rules:
- Call tools before answering; every id, severity, crew, hour, reason and number in your answer must come from a \
tool result in this conversation. If the tools do not contain the answer, say so plainly; never guess or use \
general knowledge about the plant.
- Explain scheduling only with the planner's reason codes and details (e.g. permit_lead_time, \
waiting_for_shutdown_window, crew_capacity, crowded_out). Never invent a reason.
- Always state the solver status and gap if you discuss how good the plan is; never call a FEASIBLE plan optimal.
- You cannot change the plan. If asked to, say that a constraint change in the UI triggers a replan.
- Hours count from the start of the plan (hour 0 = day 0, 00:00). Answer in plain language, at most about 120 \
words, no internal field names."""


def get_register(s: AgentSession, defect_ids: list[str] | None = None, min_severity: int | None = None,
                 needs_review_only: bool = False) -> dict:
    """Register entries, optionally filtered."""
    out = []
    for e in s.register:
        g = e.grade
        if defect_ids and e.defect_id not in defect_ids:
            continue
        if min_severity and g.severity < min_severity:
            continue
        if needs_review_only and not e.needs_review:
            continue
        senior = next((d.senior for d in e.detections if d.senior), None)
        out.append(dict(defect_id=e.defect_id, asset=e.asset.asset_id, service=e.asset.service,
                        defect_type=g.defect_type.value, severity=g.severity, confidence=round(g.confidence, 2),
                        recommended_action=g.recommended_action.value, evidence=g.evidence.visual_cues[:3],
                        location=g.evidence.location, frames=e.frames, needs_review=e.needs_review,
                        review_flags=sorted({f for d in e.detections for f in d.flags}),
                        senior_review=(dict(reason=senior["reason"], changed_decision=senior["changed_decision"],
                                            first_severity=senior["first_severity"]) if senior else None)))
    notes = [n["note"] for n in getattr(s, "voice_notes", []) if n.get("note")]
    return dict(entries=out, total_in_register=len(s.register), inspector_voice_notes=notes)


def get_schedule(s: AgentSession, defect_ids: list[str] | None = None, crew_id: str | None = None,
                 from_hour: int | None = None, to_hour: int | None = None) -> dict:
    """Plan status/gap and assignments, optionally filtered by defect, crew or time window."""
    if s.plan is None or s.scenario is None:
        return dict(error="no plan yet")
    walkdown = {e.defect_id for e in s.register}
    rows = []
    for a in sorted(s.plan.assignments, key=lambda a: a.start):
        if defect_ids and a.defect_id not in defect_ids:
            continue
        if crew_id and a.crew_id != crew_id:
            continue
        if from_hour is not None and a.end <= from_hour or to_hour is not None and a.start >= to_hour:
            continue
        rows.append(dict(defect_id=a.defect_id, crew=a.crew_id, start_hour=a.start, end_hour=a.end,
                         from_walkdown=a.defect_id in walkdown))
    return dict(status=s.plan.stats.status, gap=None if s.plan.stats.gap is None else round(s.plan.stats.gap, 4),
                scheduled=len(s.plan.assignments), unscheduled=s.plan.unscheduled,
                critical_unscheduled=s.plan.critical_unscheduled, moved_by_last_replan=s.plan.moved_jobs,
                assignments=rows[:60], truncated=len(rows) > 60)


def get_resources(s: AgentSession) -> dict:
    """Crews (skills, shifts, unavailability), shutdown windows and permits of the current scenario."""
    if s.scenario is None:
        return dict(error="no plan yet")
    sc = s.scenario.model_dump(mode="json")
    return dict(crews=sc.get("crews"), windows=sc.get("windows"), permits=sc.get("permits"),
                horizon=sc.get("horizon_days") or sc.get("horizon"), changes_so_far=s.plan_history)


COPILOT_TOOLS = {"get_register": get_register, "get_schedule": get_schedule, "explain_plan": explain_plan,
                 "get_resources": get_resources}
COPILOT_SCHEMAS = [
    _fn("get_register", "Read the defect register (severity, type, evidence, action, review flags, senior review). "
        "Filters are optional.",
        {"defect_ids": {"type": "array", "items": {"type": "string"}}, "min_severity": {"type": "integer"},
         "needs_review_only": {"type": "boolean"}}, []),
    _fn("get_schedule", "Read the plan: solver status and gap, assignments (defect, crew, start/end hour), "
        "unscheduled and moved jobs. Filters are optional.",
        {"defect_ids": {"type": "array", "items": {"type": "string"}}, "crew_id": {"type": "string"},
         "from_hour": {"type": "integer"}, "to_hour": {"type": "integer"}}, []),
    _fn("explain_plan", "The planner's structured reasons (codes, delays, blocking jobs, priority terms) for "
        "defects. The only allowed source for why a job is where it is.",
        {"defect_ids": {"type": "array", "items": {"type": "string"}}}, []),
    _fn("get_resources", "Crews, shutdown windows, permits and the constraint changes applied so far.", {}, []),
]


def copilot(session: AgentSession, **kwargs) -> WalkdownAgent:
    """A copilot agent over a finished session (keeps its own conversation for follow-ups)."""
    return WalkdownAgent(session, tools=COPILOT_TOOLS, tool_schemas=COPILOT_SCHEMAS, system_prompt=COPILOT_PROMPT,
                         cache_key="walkdown-copilot-v1", max_steps=8, **kwargs)
