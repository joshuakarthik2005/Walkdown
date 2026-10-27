"""Agent tools: perception, verification, register, planning, replanning, explanation.

Each tool works on an ``AgentSession`` and returns a compact JSON-able dict
(the model sees summaries, never masks or images). Perception and
verification results are cached per clip on WALKDOWN_DATA_DIR, so a cached
demo run makes no SAM or verifier calls; ``live=True`` ignores the cache.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.agent.clip import Clip
from backend.agent.register import Detection, RegisterEntry, build_register, to_planner_defect
from backend.clients.cost import CostLedger
from backend.perception.sam import Instance, parse_output, segment_image
from backend.planner.cpsat import solve
from backend.planner.generator import load_scenario
from backend.planner.models import Change, Plan, PlannerConfig, Scenario
from backend.planner.replan import replan
from backend.verify.schema import Grade
from backend.verify.verifier import Candidate, Verdict, verify

PROMPT = "rust"  # frozen from the dev dry run


@dataclass
class AgentSession:
    """Everything one walkdown run knows; tools read and write it."""

    clip: Clip
    ledger: CostLedger
    live: bool = False
    verify_effort: str = "low"
    # Demo path: 30 s per solve (status and gap are always reported; FEASIBLE is shown as such).
    planner_config: PlannerConfig = field(default_factory=lambda: PlannerConfig(num_workers=4, time_limit_s=30))
    base_scenario: Scenario = field(default_factory=load_scenario)
    now: int = 0
    candidates: dict[str, tuple[int, Instance]] = field(default_factory=dict)  # id -> (frame index, instance)
    frame_paths: dict[int, Path] = field(default_factory=dict)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    register: list[RegisterEntry] = field(default_factory=list)
    scenario: Scenario | None = None
    plan: Plan | None = None
    plan_history: list[dict] = field(default_factory=list)


# ---- tool implementations ---------------------------------------------------

def segment_frames(s: AgentSession, start_s: float = 0.0, end_s: float | None = None, fps: float = 1.0) -> dict:
    """Run SAM ('rust') on frames sampled from the clip; returns new candidates."""
    fps = max(0.2, min(fps, 4.0))
    frames = s.clip.frames(start_s, end_s, fps)
    new = []
    for f in frames:
        s.frame_paths[f.index] = f.path
        cache = s.clip.dir / "sam" / f"{f.path.stem}.txt"
        if cache.exists() and not s.live:
            text = cache.read_text(encoding="utf-8")
            img = f.image()
            instances = parse_output(text, img.shape[1], img.shape[0])
        else:
            res = segment_image(f.path, PROMPT, ledger=s.ledger, job="agent-sam")
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(res.raw_output, encoding="utf-8")
            instances = res.instances
        h, w = (instances[0].mask.shape if instances else (1, 1))
        for inst in instances:
            cid = f"F{f.index:05d}-{inst.object_id}"
            if cid in s.candidates:
                continue
            s.candidates[cid] = (f.index, inst)
            new.append(dict(id=cid, frame=f.index, time_s=round(f.time_s, 1), box=list(inst.box),
                            area_pct=round(100 * inst.area / (h * w), 2),
                            sam_confidence=round(inst.confidence or 0, 2)))
    return dict(frames_segmented=len(frames), new_candidates=len(new), total_candidates=len(s.candidates),
                candidates=new[:40], truncated=len(new) > 40)


def _verdict_cache(s: AgentSession, cid: str) -> Path:
    return s.clip.dir / "verify" / s.verify_effort / f"{cid}.json"


VERIFY_WORKERS = 8


def _verify_one(s: AgentSession, cid: str) -> Verdict:
    frame, inst = s.candidates[cid]
    cache = _verdict_cache(s, cid)
    if cache.exists() and not s.live:
        d = json.loads(cache.read_text(encoding="utf-8"))
        d["grade"] = Grade.model_validate(d["grade"]) if d["grade"] else None
        return Verdict(**d)
    import cv2
    image = cv2.imread(str(s.frame_paths[frame]), cv2.IMREAD_COLOR)
    v = verify(Candidate(cid, image, inst.mask, inst.box, inst.confidence), provider="meta",
               reasoning_effort=s.verify_effort, ledger=s.ledger, job="agent-verify")
    cache.parent.mkdir(parents=True, exist_ok=True)
    d = asdict(v)
    d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
    cache.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return v


def verify_candidate(s: AgentSession, candidate_ids: list[str]) -> dict:
    """Verify and grade candidates with Muse Spark (in parallel); returns one summary per candidate."""
    from concurrent.futures import ThreadPoolExecutor
    known = [c for c in dict.fromkeys(candidate_ids) if c in s.candidates]
    with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        done = dict(zip(known, pool.map(lambda c: _verify_one(s, c), known)))
    out = []
    for cid in candidate_ids:
        if cid not in done:
            out.append(dict(id=cid, error="unknown candidate id"))
            continue
        v = done[cid]
        s.verdicts[cid] = v
        g = v.grade
        out.append(dict(id=cid, is_defect=g.is_defect if g else None, defect_type=g.defect_type.value if g else None,
                        severity=g.severity if g else None, confidence=g.confidence if g else None,
                        recommended_action=g.recommended_action.value if g else None, flags=v.flags,
                        evidence=g.evidence.visual_cues[:3] if g else None))
    return dict(verified=len(out), results=out)


def build_register_tool(s: AgentSession) -> dict:
    """Group accepted, verified candidates into register entries (one per physical defect)."""
    dets = []
    for cid, v in s.verdicts.items():
        accepted = v.grade.is_defect if v.grade else True  # fail open: invalid replies go to review
        if not accepted:
            continue
        frame, inst = s.candidates[cid]
        grade = v.grade or Grade.model_validate({
            "is_defect": True, "defect_type": "other", "severity": 3, "confidence": 0.0,
            "evidence": {"visual_cues": [], "location": "", "extent": "", "mask_fit": "partial"},
            "recommended_action": "urgent_inspection"})
        dets.append(Detection(cid, frame, inst.box, grade, v.flags))
    s.register = build_register(dets, s.clip.asset, merge_across_frames=s.clip.source is not None)
    rejected = sum(1 for v in s.verdicts.values() if v.grade and not v.grade.is_defect)
    return dict(register_entries=len(s.register), rejected_candidates=rejected,
                needs_review=[e.defect_id for e in s.register if e.needs_review],
                entries=[dict(defect_id=e.defect_id, frames=e.frames, defect_type=e.grade.defect_type.value,
                              severity=e.grade.severity, confidence=e.grade.confidence,
                              recommended_action=e.grade.recommended_action.value) for e in s.register])


def _plan_summary(s: AgentSession, plan: Plan, new_ids: set[str]) -> dict:
    by_id = {a.defect_id: a for a in plan.assignments}
    return dict(
        status=plan.stats.status, solve_time_s=round(plan.stats.wall_time_s, 2),
        gap=None if plan.stats.gap is None else round(plan.stats.gap, 4),
        exposure=plan.breakdown.exposure, scheduled=len(plan.assignments), unscheduled=plan.unscheduled,
        critical_unscheduled=plan.critical_unscheduled, high_unscheduled=plan.high_unscheduled,
        moved_jobs=plan.moved_jobs,
        walkdown_defects=[dict(defect_id=d, crew=by_id[d].crew_id if d in by_id else None,
                               start_hour=by_id[d].start if d in by_id else None,
                               end_hour=by_id[d].end if d in by_id else None) for d in sorted(new_ids)],
    )


def plan_maintenance(s: AgentSession) -> dict:
    """Merge the register into the plant backlog and solve the schedule with CP-SAT."""
    new = [to_planner_defect(e, found_at=s.now) for e in s.register]
    s.scenario = s.base_scenario.model_copy(update={"defects": s.base_scenario.defects + new})
    s.plan = solve(s.scenario, s.planner_config, now=s.now)
    s.plan_history.append(dict(kind="plan", now=s.now, exposure=s.plan.breakdown.exposure))
    return _plan_summary(s, s.plan, {d.id for d in new})


CHANGE_KINDS = ("crew_unavailable", "shutdown_window_changed", "new_defect")


def normalise_change(change: dict) -> dict:
    """Flatten a change the model nested under its kind, e.g. {"crew_unavailable": {...}} (with or without "type")."""
    change = dict(change)
    for kind in CHANGE_KINDS:
        body = change.get(kind)
        if isinstance(body, dict) and kind != "new_defect":
            change.pop(kind)
            change = {**body, **change, "type": change.get("type", kind)}
        elif kind == "new_defect" and isinstance(body, dict) and "defect" not in change:
            change.pop(kind)
            change = {"type": "new_defect", "defect": body.get("defect", body)}
    return change


def replan_tool(s: AgentSession, change: dict, now_hour: int, epsilon: float | None = None) -> dict:
    """Apply a constraint change at ``now_hour`` and re-solve (two-stage, started work fixed)."""
    if s.plan is None or s.scenario is None:
        return dict(error="no plan yet; call plan_maintenance first")
    from pydantic import TypeAdapter
    change = normalise_change(change)
    parsed = TypeAdapter(Change).validate_python(change)
    r = replan(s.scenario, s.plan, parsed, now=now_hour, config=s.planner_config, epsilon=epsilon)
    s.scenario, s.plan, s.now = r.scenario, r.plan, now_hour
    s.plan_history.append(dict(kind="replan", now=now_hour, change=change, epsilon=epsilon,
                               exposure=r.plan.breakdown.exposure, moved=len(r.moved_jobs)))
    out = _plan_summary(s, r.plan, {e.defect_id for e in s.register})
    out.update(change_applied=change, epsilon=epsilon if epsilon is not None else s.planner_config.replan_epsilon,
               exposure_before=r.objective_before, newly_unscheduled=r.newly_unscheduled,
               newly_scheduled=r.newly_scheduled)
    return out


def explain_plan(s: AgentSession, defect_ids: list[str] | None = None) -> dict:
    """The planner's own structured reasons for the given defects (default: walkdown + moved + unscheduled)."""
    if s.plan is None:
        return dict(error="no plan yet")
    if not defect_ids:
        defect_ids = sorted({e.defect_id for e in s.register} | set(s.plan.moved_jobs) | set(s.plan.unscheduled))
    ex = {e.defect_id: e for e in s.plan.explanations}
    return dict(explanations=[ex[d].model_dump(mode="json") for d in defect_ids if d in ex][:30],
                unknown_ids=[d for d in defect_ids if d not in ex])


# ---- tool schemas (Chat Completions format) ----------------------------------

def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


CHANGE_SCHEMA = {
    "type": "object",
    "description": ("One constraint change, flat (not nested). crew_unavailable: crew_id, start, end. "
                    "shutdown_window_changed: window_id, new_start, new_end (omit both to cancel the window). "
                    "new_defect: defect. Hours count from plan start."),
    "properties": {
        "type": {"type": "string", "enum": ["crew_unavailable", "shutdown_window_changed", "new_defect"]},
        "crew_id": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"},
        "window_id": {"type": "string"}, "new_start": {"type": "integer"}, "new_end": {"type": "integer"},
        "defect": {"type": "object", "description": "id, asset, severity 1-5, failure_risk 0-1, repair_hours, "
                   "skill (coating|insulation|mechanical|welding), needs_shutdown"},
    },
    "required": ["type"],
}

TOOL_SCHEMAS = [
    _fn("segment_frames", "Sample frames from the walkdown clip and run SAM 3.1 ('rust') on them. Start coarse "
        "(fps 0.5-1 over the whole clip); call again with a higher fps on time ranges that need a closer look.",
        {"start_s": {"type": "number"}, "end_s": {"type": "number"}, "fps": {"type": "number"}}, []),
    _fn("verify_candidate", "Verify and grade SAM candidates with Muse Spark (rejects false positives, assigns "
        "severity 1-5, evidence and action). Pass up to 20 candidate ids per call.",
        {"candidate_ids": {"type": "array", "items": {"type": "string"}}}, ["candidate_ids"]),
    _fn("build_register", "Build the defect register from all verified, accepted candidates (merges repeated "
        "sightings of the same defect).", {}, []),
    _fn("plan_maintenance", "Add the register's defects to the plant's maintenance backlog and compute the "
        "risk-optimal repair schedule with CP-SAT.", {}, []),
    _fn("replan", "Apply a constraint change and re-solve. Work already started stays fixed. epsilon (0-0.1) "
        "trades risk for stability: higher moves fewer jobs.",
        {"change": CHANGE_SCHEMA, "now_hour": {"type": "integer"}, "epsilon": {"type": "number"}},
        ["change", "now_hour"]),
    _fn("explain_plan", "Get the planner's structured reasons (codes, delays, blocking jobs) for defects. Use "
        "these, and only these, to explain the plan.",
        {"defect_ids": {"type": "array", "items": {"type": "string"}}}, []),
]

TOOLS = {
    "segment_frames": segment_frames,
    "verify_candidate": verify_candidate,
    "build_register": build_register_tool,
    "plan_maintenance": plan_maintenance,
    "replan": replan_tool,
    "explain_plan": explain_plan,
}
