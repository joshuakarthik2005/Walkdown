"""Agent tools: perception, verification, register, planning, replanning, explanation.

Each tool works on an ``AgentSession`` and returns a compact JSON-able dict
(the model sees summaries, never masks or images). Perception and
verification results are cached per clip on WALKDOWN_DATA_DIR, so a cached
demo run makes no SAM or verifier calls; ``live=True`` ignores the cache.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.agent.clip import Clip
from backend.agent.register import Detection, RegisterEntry, build_register, to_planner_defect
from backend.clients.cost import CostLedger
from backend.perception.boxes import box_masks, merge_with_text, parse_box_output, propose_boxes
from backend.perception.sam import Instance, parse_output, segment_image, segment_video
from backend.perception.sam_open import segment_boxes_open, segment_images_open, segment_video_open, to_instances
from backend.planner.cpsat import solve
from backend.planner.generator import load_scenario
from backend.planner.models import Change, Plan, PlannerConfig, Scenario
from backend.verify.sensitivity import PROMPT_VERSION
from backend.planner.packages import PackageConfig, build_packages, choose_view, package_of, plan_metrics, setup_hours_saved
from backend.planner.replan import replan
from backend.verify.schema import Grade
from backend.verify.escalation import SeniorReview, senior_review
from backend.verify.verifier import Candidate, Verdict, verify

PROMPT = "rust"  # frozen from the dev dry run
# Demo plant backlog: the first 12 jobs of the demo scenario (same crews, windows, permits). Measured: with up
# to 6 walkdown defects added, plan and replans solve to OPTIMAL within the 30 s demo limit (docs/DECISIONS.md).
DEMO_BACKLOG_SIZE = 12


def demo_backlog(size: int = DEMO_BACKLOG_SIZE) -> Scenario:
    """The plant's existing maintenance backlog used by the demo."""
    sc = load_scenario()
    return sc.model_copy(update={"name": "demo-plant", "defects": sc.defects[:size]})


@dataclass
class AgentSession:
    """Everything one walkdown run knows; tools read and write it."""

    clip: Clip
    ledger: CostLedger
    live: bool = False
    verify_effort: str = "low"
    box_proposals: bool = True  # text + boxes + verifier is the default pipeline (benchmark/RESULTS.md section 4)
    sam_backend: str = "meta"  # "meta" (hosted SAM 3.1) or "modal" (SAM 3.1 open weights, On-prem mode)
    packages: PackageConfig = field(default_factory=PackageConfig)  # work-package grouping of register defects
    provider: str = "meta"  # "meta" (hosted Muse Spark) or "baseten" (open-weight Muse Spark Open)
    senior_review: bool = True  # escalate severe/uncertain grades to Muse Wonder (Cloud mode only)
    # Detection sensitivity (backend/verify/sensitivity.py): "high_recall" (default, prompt v1) or "balanced"
    # (look-alike checklist prompt v2). Cloud mode only; On-prem always uses Muse Spark Open with v1.
    sensitivity: str = "high_recall"
    # Demo path: 30 s per solve (status and gap are always reported; FEASIBLE is shown as such).
    planner_config: PlannerConfig = field(default_factory=lambda: PlannerConfig(time_limit_s=30))
    base_scenario: Scenario = field(default_factory=lambda: demo_backlog())
    now: int = 0
    candidates: dict[str, tuple[int, Instance]] = field(default_factory=dict)  # id -> (frame index, instance)
    frame_paths: dict[int, Path] = field(default_factory=dict)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    reviews: dict[str, SeniorReview] = field(default_factory=dict)  # candidate id -> senior review
    voice_notes: list[dict] = field(default_factory=list)  # backend.voice.notes.process results
    tracks: dict[str, list[int]] = field(default_factory=dict)  # track candidate id -> every frame it was seen on
    register: list[RegisterEntry] = field(default_factory=list)
    scenario: Scenario | None = None
    plan: Plan | None = None
    plan_history: list[dict] = field(default_factory=list)
    # Both plans of the walkdown: "individual" (one job per defect) and, when defects can be grouped, "grouped"
    # (work packages); each {"scenario", "plan", "jobs"}. plan_view is the one the agent uses (s.scenario/s.plan).
    variants: dict[str, dict] = field(default_factory=dict)
    plan_view: str = "individual"
    view_reason: str = ""


# ---- tool implementations ---------------------------------------------------

def _open_cache(s: AgentSession, f) -> Path:
    return s.clip.dir / "sam_open" / f"{f.path.stem}.json"


def _open_box_caches(s: AgentSession, f) -> tuple[Path, Path]:
    return s.clip.dir / "boxes_open" / f"{f.path.stem}.json", s.clip.dir / "sam_open_boxes" / f"{f.path.stem}.json"


def _prefetch_open(s: AgentSession, frames: list) -> None:
    """On-prem mode: segment every uncached frame with SAM 3.1 open weights in one Modal call; with box
    proposals, ask Muse Spark Open for boxes on all those frames in parallel, then segment them in one call."""
    todo = [f for f in frames if s.live or not _open_cache(s, f).exists()]
    if todo:
        for f, records in zip(todo, segment_images_open([f.path for f in todo], PROMPT, ledger=s.ledger,
                                                        job="agent-sam-open")):
            _open_cache(s, f).parent.mkdir(exist_ok=True)
            _open_cache(s, f).write_text(json.dumps(records), encoding="utf-8")
    if not s.box_proposals:
        return
    todo = [f for f in frames if s.live or not _open_box_caches(s, f)[1].exists()]
    if not todo:
        return

    def boxes_for(f) -> list:
        box_cache = _open_box_caches(s, f)[0]
        if box_cache.exists() and not s.live:
            return [tuple(b) for b in json.loads(box_cache.read_text(encoding="utf-8"))]
        h, w = f.image().shape[:2]
        boxes = propose_boxes(f.path, w, h, ledger=s.ledger, job="agent-box-propose-open", provider=s.provider)
        box_cache.parent.mkdir(exist_ok=True)
        box_cache.write_text(json.dumps(boxes), encoding="utf-8")
        return boxes

    with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        boxes = list(pool.map(boxes_for, todo))
    for f, records in zip(todo, segment_boxes_open([f.path for f in todo], boxes, ledger=s.ledger,
                                                   job="agent-box-sam-open")):
        sam_cache = _open_box_caches(s, f)[1]
        sam_cache.parent.mkdir(exist_ok=True)
        sam_cache.write_text(json.dumps(records), encoding="utf-8")


def _text_instances(s: AgentSession, f) -> list[Instance]:
    """SAM 3.1 'rust' instances on one frame (cached)."""
    if s.sam_backend == "modal":
        return to_instances(json.loads(_open_cache(s, f).read_text(encoding="utf-8")), frame=0)
    cache = s.clip.dir / "sam" / f"{f.path.stem}.txt"
    if cache.exists() and not s.live:
        img = f.image()
        return parse_output(cache.read_text(encoding="utf-8"), img.shape[1], img.shape[0])
    res = segment_image(f.path, PROMPT, ledger=s.ledger, job="agent-sam")
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(res.raw_output, encoding="utf-8")
    return res.instances


def _box_instances_open(s: AgentSession, f) -> list[Instance]:
    """On-prem box-prompted instances (Muse Spark Open boxes, SAM 3.1 open weights), filled by _prefetch_open."""
    return to_instances(json.loads(_open_box_caches(s, f)[1].read_text(encoding="utf-8")), frame=0)


def _box_instances(s: AgentSession, f) -> list[Instance]:
    """Box-prompted SAM 3.1 instances on one frame: Muse Spark boxes (minimal effort), then SAM (cached)."""
    if s.sam_backend == "modal":
        return _box_instances_open(s, f)
    img = f.image()
    h, w = img.shape[:2]
    box_cache = s.clip.dir / "boxes" / f"{f.path.stem}.json"
    sam_cache = s.clip.dir / "sam_boxes" / f"{f.path.stem}.txt"
    if sam_cache.exists() and not s.live:
        return parse_box_output(sam_cache.read_text(encoding="utf-8"), w, h)
    if box_cache.exists() and not s.live:
        boxes = [tuple(b) for b in json.loads(box_cache.read_text(encoding="utf-8"))]
    else:
        boxes = propose_boxes(f.path, w, h, ledger=s.ledger, job="agent-box-propose")
        box_cache.parent.mkdir(exist_ok=True)
        box_cache.write_text(json.dumps(boxes), encoding="utf-8")
    raw = box_masks(f.path, boxes, w, h, ledger=s.ledger, job="agent-box-sam")
    sam_cache.parent.mkdir(exist_ok=True)
    sam_cache.write_text(raw, encoding="utf-8")
    return parse_box_output(raw, w, h)


def segment_frames(s: AgentSession, start_s: float = 0.0, end_s: float | None = None, fps: float = 1.0) -> dict:
    """Run SAM ('rust') plus Muse Spark box proposals on frames sampled from the clip; returns new candidates.

    Text and box perception for a frame run in parallel; their masks are merged by overlap (text + boxes,
    the default pipeline; ``s.box_proposals=False`` gives text only).
    """
    fps = max(0.2, min(fps, 4.0))
    frames = s.clip.frames(start_s, end_s, fps)
    if s.sam_backend == "modal":
        _prefetch_open(s, frames)
    new = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in frames:
            s.frame_paths[f.index] = f.path
            text_job = pool.submit(_text_instances, s, f)
            box_job = pool.submit(_box_instances, s, f) if s.box_proposals else None
            text = text_job.result()
            merged = merge_with_text(text, box_job.result()) if box_job else [(i.object_id, i) for i in text]
            for obj, inst in merged:
                h, w = inst.mask.shape
                cid = f"F{f.index:05d}-{obj}"
                if cid in s.candidates:
                    continue
                s.candidates[cid] = (f.index, inst)
                new.append(dict(id=cid, frame=f.index, time_s=round(f.time_s, 1), box=list(inst.box),
                                area_pct=round(100 * inst.area / (h * w), 2),
                                sam_confidence=round(inst.confidence or 0, 2),
                                source="text" if not obj.startswith("b") else "box"))
    return dict(frames_segmented=len(frames), new_candidates=len(new), total_candidates=len(s.candidates),
                candidates=new[:40], truncated=len(new) > 40)


def best_track_frames(instances: list[Instance]) -> dict[str, tuple[Instance, list[int]]]:
    """Per SAM video track (object id): the instance on its best frame (largest area x confidence) and all frames."""
    by_track: dict[str, list[Instance]] = {}
    for inst in instances:
        by_track.setdefault(inst.object_id, []).append(inst)
    out = {}
    for obj, insts in by_track.items():
        best = max(insts, key=lambda i: (i.area * (i.confidence if i.confidence is not None else 1.0), -i.frame))
        out[obj] = (best, sorted({i.frame for i in insts}))
    return out


def track_video(s: AgentSession, fps: float = 2.0) -> dict:
    """F3: SAM 3.1 video tracking over the whole clip; one candidate per physical defect (track), on its best frame."""
    if s.clip.source is None:
        return dict(error="this clip is a set of photos; use segment_frames")
    fps = max(0.5, min(fps, 4.0))
    frames = s.clip.frames(0.0, None, fps)  # the same time grid as the resampled clip: frame i at i / fps s
    cache = s.clip.dir / "sam_video" / f"rust_{fps:g}fps.txt"
    if s.sam_backend == "modal":
        cache = s.clip.dir / "sam_open_video" / f"rust_{fps:g}fps.json"
        if cache.exists() and not s.live:
            records = json.loads(cache.read_text(encoding="utf-8"))
        else:
            records = segment_video_open([f.path for f in frames], PROMPT, ledger=s.ledger, job="agent-sam-open-video")
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(records), encoding="utf-8")
        instances = to_instances(records)
    elif cache.exists() and not s.live:
        h, w = frames[0].image().shape[:2]
        instances = parse_output(cache.read_text(encoding="utf-8"), w, h, video=True)
    else:
        res = segment_video(s.clip.source, PROMPT, sample_fps=fps, ledger=s.ledger, job="agent-sam-video")
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(res.raw_output, encoding="utf-8")
        instances = res.instances
    new = []
    for obj, (inst, idx) in best_track_frames([i for i in instances if i.frame < len(frames)]).items():
        cid = f"T{obj}"
        if cid in s.candidates:
            continue
        f = frames[inst.frame]
        for i in idx:
            s.frame_paths[frames[i].index] = frames[i].path
        s.candidates[cid] = (f.index, inst)
        s.tracks[cid] = [frames[i].index for i in idx]
        h, w = inst.mask.shape
        new.append(dict(id=cid, best_frame=f.index, time_s=round(f.time_s, 1), seen_on_frames=len(idx),
                        first_s=round(frames[idx[0]].time_s, 1), last_s=round(frames[idx[-1]].time_s, 1),
                        area_pct=round(100 * inst.area / (h * w), 2), sam_confidence=round(inst.confidence or 0, 2)))
    return dict(frames_tracked=len(frames), tracks=len(new), total_candidates=len(s.candidates), candidates=new[:40],
                truncated=len(new) > 40)


def _prompt_version(s: AgentSession) -> str:
    return PROMPT_VERSION.get(s.sensitivity, "v1") if s.provider == "meta" else "v1"


def _verdict_cache(s: AgentSession, cid: str) -> Path:
    sub = s.verify_effort if s.provider == "meta" else f"{s.provider}-{s.verify_effort}"
    if _prompt_version(s) != "v1":
        sub += f"-{_prompt_version(s)}"
    if s.sam_backend != "meta":  # open-weights SAM gives different masks under the same candidate ids
        sub += f"-sam-{s.sam_backend}"
    return s.clip.dir / "verify" / sub / f"{cid}.json"


VERIFY_WORKERS = 8


def _load_verdict(d: dict) -> Verdict:
    d = dict(d)
    d["grade"] = Grade.model_validate(d["grade"]) if d["grade"] else None
    return Verdict(**d)


def _dump_verdict(v: Verdict) -> dict:
    d = asdict(v)
    d["grade"] = v.grade.model_dump(mode="json") if v.grade else None
    return d


def _verify_one(s: AgentSession, cid: str) -> tuple[Verdict, SeniorReview | None]:
    """First-pass verdict (cached), then senior review when the grade needs it (cached separately)."""
    import cv2
    frame, inst = s.candidates[cid]
    obj = cid.split("-", 1)[1] if "-" in cid else cid
    cand = lambda: Candidate(cid, cv2.imread(str(s.frame_paths[frame]), cv2.IMREAD_COLOR), inst.mask,  # noqa: E731
                             inst.box, inst.confidence, source="box" if obj.startswith("b") else "text")
    cache = _verdict_cache(s, cid)
    if cache.exists() and not s.live:
        v = _load_verdict(json.loads(cache.read_text(encoding="utf-8")))
    else:
        v = verify(cand(), provider=s.provider, reasoning_effort=s.verify_effort, ledger=s.ledger, job="agent-verify",
                   prompt_version=_prompt_version(s))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(_dump_verdict(v), indent=1), encoding="utf-8")
    if not (s.senior_review and s.provider == "meta"):
        return v, None
    senior_cache = cache.parent.with_name(cache.parent.name + "-senior") / cache.name
    if senior_cache.exists() and not s.live:
        d = json.loads(senior_cache.read_text(encoding="utf-8"))
        final, review = _load_verdict(d["verdict"]), (SeniorReview(**d["review"]) if d["review"] else None)
        if review and v.grade and v.grade.is_defect and final.grade and not final.grade.is_defect:
            # Cached before the fail-safe rule: a disputed defect stays, flagged for human review.
            final = Verdict(**{**asdict(v), "grade": v.grade, "flags": v.flags + ["senior_disputed"]})
        return final, review
    final, review = senior_review(cand(), v, effort="low", ledger=s.ledger, job="agent-senior-review")
    if review is not None or not senior_cache.exists():
        senior_cache.parent.mkdir(parents=True, exist_ok=True)
        senior_cache.write_text(json.dumps(dict(verdict=_dump_verdict(final),
                                                review=review.to_dict() if review else None), indent=1),
                                encoding="utf-8")
    return final, review


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
        v, review = done[cid]
        s.verdicts[cid] = v
        if review is not None:
            s.reviews[cid] = review
        g = v.grade
        out.append(dict(id=cid, is_defect=g.is_defect if g else None, defect_type=g.defect_type.value if g else None,
                        severity=g.severity if g else None, confidence=g.confidence if g else None,
                        recommended_action=g.recommended_action.value if g else None, flags=v.flags,
                        evidence=g.evidence.visual_cues[:3] if g else None,
                        senior_review=(dict(reason=review.reason, first_severity=review.first_severity,
                                            changed_decision=review.changed_decision,
                                            changed_severity=review.changed_severity) if review else None)))
    return dict(verified=len(out), senior_reviews=sum(1 for r in out if r.get("senior_review")), results=out)


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
        review = s.reviews.get(cid)
        dets.append(Detection(cid, frame, inst.box, grade, v.flags, review.to_dict() if review else None,
                              s.tracks.get(cid, [])))
    s.register = build_register(dets, s.clip.asset, merge_across_frames=s.clip.source is not None)
    rejected = sum(1 for v in s.verdicts.values() if v.grade and not v.grade.is_defect)
    return dict(register_entries=len(s.register), rejected_candidates=rejected,
                needs_review=[e.defect_id for e in s.register if e.needs_review],
                entries=[dict(defect_id=e.defect_id, frames=e.frames, defect_type=e.grade.defect_type.value,
                              severity=e.grade.severity, confidence=e.grade.confidence,
                              recommended_action=e.grade.recommended_action.value,
                              service=e.asset.service) for e in s.register])


def _plan_summary(s: AgentSession, plan: Plan, new_ids: set[str]) -> dict:
    by_id = {a.defect_id: a for a in plan.assignments}
    jobs = {d.id: d for d in s.scenario.defects} if s.scenario else {}
    return dict(
        status=plan.stats.status, solve_time_s=round(plan.stats.wall_time_s, 2),
        gap=None if plan.stats.gap is None else round(plan.stats.gap, 4),
        exposure=plan.breakdown.exposure, scheduled=len(plan.assignments), unscheduled=plan.unscheduled,
        critical_unscheduled=plan.critical_unscheduled, high_unscheduled=plan.high_unscheduled,
        moved_jobs=plan.moved_jobs,
        walkdown_jobs=[dict(job_id=d, register_defects=(jobs[d].members or [d]) if d in jobs else [d],
                            repair_hours=jobs[d].repair_hours if d in jobs else None,
                            crew=by_id[d].crew_id if d in by_id else None,
                            start_hour=by_id[d].start if d in by_id else None,
                            end_hour=by_id[d].end if d in by_id else None) for d in sorted(new_ids)],
    )


def _use_view(s: AgentSession, view: str) -> None:
    """Make one plan variant current: s.scenario, s.plan and each register entry's planner job id."""
    s.plan_view = view
    v = s.variants[view]
    s.scenario, s.plan = v["scenario"], v["plan"]
    owner = package_of(v["jobs"])
    for e in s.register:
        e.package_id = owner.get(e.defect_id, e.package_id or e.defect_id)


def compare_views(s: AgentSession) -> dict:
    """Both plans side by side on the per-defect objective (exposure, makespan, status/gap, setup hours saved)."""
    flat = s.variants["individual"]["scenario"]
    out = dict(chosen=s.plan_view, reason=s.view_reason)
    for name, v in s.variants.items():
        m = plan_metrics(flat, s.planner_config, v["plan"], v["jobs"] if name == "grouped" else None)
        m["setup_hours_saved"] = setup_hours_saved(v["jobs"], s.variants["individual"]["jobs"]) if name == "grouped" else 0
        out[name] = m
    return out


def plan_maintenance(s: AgentSession) -> dict:
    """Merge the register into the plant backlog and solve the schedule with CP-SAT.

    Solves the individual plan and, when defects can be grouped, the work-package plan in parallel; the adaptive
    rule (``choose_view``) picks which one the agent uses. Both stay available for the UI.
    """
    defects = [to_planner_defect(e, found_at=s.now) for e in s.register]
    grouped = build_packages(defects, {e.defect_id: e.frames for e in s.register}, s.base_scenario.crews, s.packages,
                             planner=s.planner_config)
    jobs = {"individual": defects}
    if any(j.members for j in grouped):
        jobs["grouped"] = grouped
    scenarios = {k: s.base_scenario.model_copy(update={"defects": s.base_scenario.defects + js}) for k, js in jobs.items()}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        plans = dict(zip(jobs, pool.map(lambda k: solve(scenarios[k], s.planner_config, now=s.now), jobs)))
    s.variants = {k: dict(scenario=scenarios[k], plan=plans[k], jobs=jobs[k]) for k in jobs}
    view, s.view_reason = choose_view(plans["individual"], plans.get("grouped"), s.packages)
    _use_view(s, view)
    s.plan_history.append(dict(kind="plan", now=s.now, exposure=s.plan.breakdown.exposure, view=view))
    out = _plan_summary(s, s.plan, {d.id for d in jobs[view]})
    out.update(plan_view=view, view_reason=s.view_reason,
               comparison={k: v for k, v in compare_views(s).items() if k in ("individual", "grouped")})
    return out


def _walkdown_job_ids(s: AgentSession) -> set[str]:
    """Planner job ids of the walkdown: work packages and ungrouped register defects."""
    return {e.package_id or e.defect_id for e in s.register}


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
    names = list(s.variants) or [s.plan_view]
    if not s.variants:
        s.variants = {s.plan_view: dict(scenario=s.scenario, plan=s.plan, jobs=[])}
    with ThreadPoolExecutor(max_workers=len(names)) as pool:  # keep both plans current for the UI
        results = dict(zip(names, pool.map(
            lambda k: replan(s.variants[k]["scenario"], s.variants[k]["plan"], parsed, now=now_hour,
                             config=s.planner_config, epsilon=epsilon), names)))
    for k, res in results.items():
        s.variants[k] = dict(s.variants[k], scenario=res.scenario, plan=res.plan)
    r = results[s.plan_view]
    s.now = now_hour
    _use_view(s, s.plan_view)
    s.plan_history.append(dict(kind="replan", now=now_hour, change=change, epsilon=epsilon,
                               exposure=r.plan.breakdown.exposure, moved=len(r.moved_jobs)))
    out = _plan_summary(s, r.plan, _walkdown_job_ids(s))
    out.update(change_applied=change, epsilon=epsilon if epsilon is not None else s.planner_config.replan_epsilon,
               exposure_before=r.objective_before, newly_unscheduled=r.newly_unscheduled,
               newly_scheduled=r.newly_scheduled)
    return out


def explain_plan(s: AgentSession, defect_ids: list[str] | None = None) -> dict:
    """The planner's own structured reasons for the given defects (default: walkdown + moved + unscheduled)."""
    if s.plan is None:
        return dict(error="no plan yet")
    if not defect_ids:
        defect_ids = sorted(_walkdown_job_ids(s) | set(s.plan.moved_jobs) | set(s.plan.unscheduled))
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
    _fn("segment_frames", "Sample frames from the walkdown clip and run SAM 3.1 ('rust') plus Muse Spark box proposals "
        "(segmented by SAM 3.1) on them; masks are merged per frame. Start coarse "
        "(fps 0.5-1 over the whole clip); call again with a higher fps on time ranges that need a closer look.",
        {"start_s": {"type": "number"}, "end_s": {"type": "number"}, "fps": {"type": "number"}}, []),
    _fn("track_video", "Video clips only: track corrosion through the whole clip with SAM 3.1 video tracking. "
        "Returns one candidate per tracked physical defect (on its best frame), so repeat sightings are already "
        "merged. Prefer this over segment_frames for video; use segment_frames for photo sets.",
        {"fps": {"type": "number"}}, []),
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
    "track_video": track_video,
    "verify_candidate": verify_candidate,
    "build_register": build_register_tool,
    "plan_maintenance": plan_maintenance,
    "replan": replan_tool,
    "explain_plan": explain_plan,
}
