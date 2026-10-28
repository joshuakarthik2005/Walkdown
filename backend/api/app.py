"""Walkdown HTTP API (FastAPI).

Endpoints:
  POST /clips                    upload a walkdown video, or photos, plus asset metadata -> clip_id
  POST /runs                     start an agent run on a clip (background thread) -> run_id
  GET  /runs/{id}                status, final answer, cost
  GET  /runs/{id}/trace          structured trace (tool calls with timing and cost); ?since=N for polling
  GET  /runs/{id}/register       verified defect register
  GET  /runs/{id}/plan           current maintenance plan (assignments, stats, explanations)
  POST /runs/{id}/changes        constraint change + epsilon; the agent replans and explains
  POST /runs/{id}/ask            inspector copilot: question about the register and plan (read-only tools)
  POST /runs/{id}/voice          inspector voice note (WAV): transcribed and structured, attached to the run
  GET  /runs/{id}/report.pdf     inspection report; /work_orders.csv and .json: CMMS-style work orders

Runs live in memory (one process); caches and clips are on WALKDOWN_DATA_DIR.

    .venv\\Scripts\\python.exe -m uvicorn backend.api.app:app --port 8000
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.agent.clip import CLIPS_DIR, Clip, create_clip
from backend.agent.copilot import copilot
from backend.agent.loop import TraceEvent, WalkdownAgent
from backend.agent.tools import AgentSession, compare_views
from backend.clients.cost import CostLedger
from backend.planner.models import ServiceType
from backend.planner.packages import package_of

app = FastAPI(title="Walkdown API", version="0.1.0")
# Local UI only: any port on localhost / 127.0.0.1.
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])

MAX_UPLOAD_MB = 500


class RunState:
    """One agent run and its follow-up turns."""

    def __init__(self, run_id: str, agent: WalkdownAgent) -> None:
        self.run_id = run_id
        self.agent = agent
        self.status: Literal["running", "done", "error"] = "running"
        self.answers: list[str] = []
        self.error: str | None = None
        self.started_at = time.time()
        self.lock = threading.Lock()
        self.copilot: WalkdownAgent | None = None  # created on the first question

    def turn(self, message: str) -> None:
        with self.lock:
            self.status = "running"
            try:
                self.answers.append(self.agent.run(message))
                self.status = "done"
            except Exception as err:  # surfaced through GET /runs/{id}
                self.status, self.error = "error", f"{type(err).__name__}: {err}"


RUNS: dict[str, RunState] = {}


def _run(run_id: str) -> RunState:
    if run_id not in RUNS:
        raise HTTPException(404, "unknown run")
    return RUNS[run_id]


@app.post("/clips")
async def upload_clip(files: list[UploadFile] = File(...), asset_id: str = Form(...), asset_type: str = Form("pipe"),
                      pressurised: bool = Form(True), location: str = Form(""),
                      service: str = Form("")) -> dict:
    """Store one video, or several photos, as a new clip."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", asset_id):
        raise HTTPException(400, "asset_id: letters, digits, . _ - only")
    clip_id = f"clip-{uuid.uuid4().hex[:10]}"
    with tempfile.TemporaryDirectory() as tmp:
        saved = []
        for f in files:
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in {".mp4", ".mov", ".jpg", ".jpeg", ".png"}:
                raise HTTPException(400, f"unsupported file type {suffix!r}")
            path = Path(tmp) / f"{len(saved):04d}{suffix}"
            with path.open("wb") as out:
                shutil.copyfileobj(f.file, out, length=1 << 20)
            if path.stat().st_size > MAX_UPLOAD_MB << 20:
                raise HTTPException(413, "file too large")
            saved.append(path)
        videos = [p for p in saved if p.suffix in {".mp4", ".mov"}]
        if len(videos) > 1 or (videos and len(saved) > 1):
            raise HTTPException(400, "upload one video, or photos only")
        if service and service not in {s.value for s in ServiceType}:
            raise HTTPException(400, f"unknown service {service!r}")
        asset = dict(asset_id=asset_id, asset_type=asset_type, pressurised=pressurised, location=location,
                     service=service or None)
        clip = create_clip(clip_id, video=videos[0] if videos else None, photos=None if videos else saved, asset=asset)
    return dict(clip_id=clip_id, duration_s=clip.duration_s, asset=asset)


class RunRequest(BaseModel):
    clip_id: str
    live: bool = Field(False, description="Ignore cached perception/verification results and call the APIs.")
    verify_effort: Literal["minimal", "low", "medium"] = "minimal"
    agent_effort: Literal["minimal", "low", "medium"] = "low"
    provider: Literal["meta", "baseten"] = Field(
        "meta", description="meta: Cloud mode (hosted SAM 3.1, Muse Spark, Muse Wonder); baseten: On-prem mode, open "
                            "weights only (SAM 3.1 on Modal, Muse Spark Open on Baseten for agent and verifier).")
    message: str | None = None


@app.post("/runs")
def start_run(req: RunRequest) -> dict:
    """Start the agent on a clip in a background thread."""
    try:
        clip = Clip(req.clip_id)
    except FileNotFoundError:
        raise HTTPException(404, "unknown clip") from None
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    session = AgentSession(clip=clip, ledger=CostLedger(clip.dir / "cost_ledger.jsonl"), live=req.live,
                           verify_effort=req.verify_effort, provider=req.provider,
                           # On-prem mode uses open weights only: SAM 3.1 open weights on Modal, box proposals from
                           # Muse Spark Open, and no senior review (Muse Wonder).
                           sam_backend="modal" if req.provider == "baseten" else "meta")
    state = RunState(run_id, WalkdownAgent(session, reasoning_effort=req.agent_effort))
    RUNS[run_id] = state
    message = req.message or (f"New walkdown clip of {clip.asset.asset_id}"
                              + (f" ({clip.asset.location})" if clip.asset.location else "")
                              + " is uploaded. Inspect it, build the register, plan the repairs and explain the plan.")
    threading.Thread(target=state.turn, args=(message,), daemon=True).start()
    return dict(run_id=run_id, status=state.status)


@app.get("/runs/{run_id}")
def run_status(run_id: str) -> dict:
    st = _run(run_id)
    s = st.agent.s
    return dict(run_id=run_id, status=st.status, error=st.error, answers=st.answers,
                steps=len(st.agent.trace), usd=s.ledger.total(), elapsed_s=time.time() - st.started_at,
                now_hour=s.now)


@app.get("/runs/{run_id}/trace")
def run_trace(run_id: str, since: int = 0) -> dict:
    st = _run(run_id)
    events: list[TraceEvent] = st.agent.trace[since:]
    return dict(status=st.status, next=since + len(events), events=[e.model_dump(mode="json") for e in events])


@app.get("/runs/{run_id}/register")
def run_register(run_id: str) -> dict:
    s = _run(run_id).agent.s
    return dict(asset=s.clip.asset.__dict__, voice_notes=s.voice_notes, entries=[dict(
        defect_id=e.defect_id, package_id=e.package_id, frames=e.frames, needs_review=e.needs_review,
        grade=e.grade.model_dump(mode="json"),
        detections=[dict(candidate_id=d.candidate_id, frame=d.frame, box=list(d.box), flags=d.flags, senior=d.senior)
                    for d in e.detections]) for e in s.register])


@app.get("/runs/{run_id}/plan")
def run_plan(run_id: str, view: Literal["grouped", "individual"] | None = None) -> dict:
    """The plan the agent uses, or the other variant (``view``), with the grouped-vs-individual comparison."""
    s = _run(run_id).agent.s
    if s.plan is None:
        raise HTTPException(409, "no plan yet")
    view = view if view in s.variants else s.plan_view
    v = s.variants.get(view, dict(scenario=s.scenario, plan=s.plan, jobs=[]))
    if view == "individual" or not v["jobs"]:
        job_ids = {e.defect_id for e in s.register}
    else:
        owner = package_of(v["jobs"])
        job_ids = {owner.get(e.defect_id, e.defect_id) for e in s.register}
    return dict(plan=json.loads(v["plan"].model_dump_json()), scenario=json.loads(v["scenario"].model_dump_json()),
                history=s.plan_history, view=view, chosen_view=s.plan_view, views=sorted(s.variants),
                comparison=compare_views(s) if "individual" in s.variants else None,
                # planner job ids of the walkdown (work packages, or single defects) for the Gantt
                walkdown_defect_ids=sorted(job_ids))


class ChangeRequest(BaseModel):
    change: dict = Field(description="A planner Change: crew_unavailable, shutdown_window_changed or new_defect.")
    now_hour: int = Field(ge=0)
    epsilon: float = Field(0.02, ge=0, le=0.5, description="Stability vs risk: higher moves fewer jobs.")


@app.post("/runs/{run_id}/changes")
def post_change(run_id: str, req: ChangeRequest) -> dict:
    """Ask the agent to replan for a constraint change (it calls replan, then explain_plan)."""
    st = _run(run_id)
    if st.status == "running":
        raise HTTPException(409, "run is busy")
    if st.agent.s.plan is None:
        raise HTTPException(409, "no plan yet")
    message = (f"Constraint change at hour {req.now_hour}: {json.dumps(req.change)}. Replan with epsilon "
               f"{req.epsilon} and explain what changed.")
    st.status = "running"  # before the thread starts, so a poll right after this call cannot see "done"
    threading.Thread(target=st.turn, args=(message,), daemon=True).start()
    return dict(run_id=run_id, status="running")


@app.post("/runs/{run_id}/voice")
async def voice_note(run_id: str, audio: UploadFile = File(...)) -> dict:
    """Transcribe an inspector's WAV voice note (Muse Voice Transcribe) and extract structured fields."""
    from backend.voice.notes import process
    st = _run(run_id)
    if Path(audio.filename or "").suffix.lower() != ".wav":
        raise HTTPException(400, "voice notes must be WAV")
    data = await audio.read()
    if len(data) > 50 << 20:
        raise HTTPException(413, "file too large")
    result = process(data, ledger=st.agent.s.ledger)
    st.agent.s.voice_notes.append(result)
    return result


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.post("/runs/{run_id}/ask")
def ask(run_id: str, req: AskRequest) -> dict:
    """Inspector copilot: answers from the register, plan and planner reasons only (read-only tools)."""
    st = _run(run_id)
    if st.status == "running":
        raise HTTPException(409, "run is busy")
    if not st.agent.s.register and st.agent.s.plan is None:
        raise HTTPException(409, "nothing to ask about yet")
    with st.lock:
        if st.copilot is None:
            st.copilot = copilot(st.agent.s, reasoning_effort="low")
        spent, start = st.agent.s.ledger.total(), len(st.copilot.trace)
        answer = st.copilot.run(req.question)
        events = st.copilot.trace[start:]
    return dict(answer=answer, usd=st.agent.s.ledger.total() - spent,
                tool_calls=[dict(name=e.name, args=e.args, summary=e.summary) for e in events if e.kind == "tool"])


@app.get("/runs/{run_id}/frames")
def run_frames(run_id: str) -> dict:
    """Frames that have register detections, with the detections on each."""
    s = _run(run_id).agent.s
    frames: dict[int, list[dict]] = {}
    for e in s.register:
        for d in e.detections:
            frames.setdefault(d.frame, []).append(dict(defect_id=e.defect_id, candidate_id=d.candidate_id,
                                                       box=list(d.box), severity=d.grade.severity))
    return dict(frames=[dict(frame=f, detections=v) for f, v in sorted(frames.items())])


@app.get("/runs/{run_id}/frames/{frame}.jpg")
def run_frame_image(run_id: str, frame: int) -> Response:
    """One frame with every register detection outlined, coloured by severity, and labelled."""
    from backend.reports.export import render_frame

    s = _run(run_id).agent.s
    if frame not in s.frame_paths:
        raise HTTPException(404, "unknown frame")
    return Response(render_frame(s, frame), media_type="image/jpeg")


def _plan_start(plan_start: str | None):
    from datetime import datetime
    try:
        return datetime.fromisoformat(plan_start) if plan_start else datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(400, "plan_start must be an ISO date-time") from None


@app.get("/runs/{run_id}/report.pdf")
def run_report(run_id: str, plan_start: str | None = None) -> Response:
    """Inspection report PDF (register, frames, proposed work orders, planner reasons, safe-use notice)."""
    from backend.reports.export import pdf_report
    s = _run(run_id).agent.s
    if not s.register:
        raise HTTPException(409, "no register yet")
    return Response(pdf_report(s, _plan_start(plan_start)), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="walkdown-{s.clip.asset.asset_id}.pdf"'})


@app.get("/runs/{run_id}/work_orders.{fmt}")
def run_work_orders(run_id: str, fmt: Literal["csv", "json"], plan_start: str | None = None) -> Response:
    """Proposed work orders in a CMMS-compatible flat format (not a certified integration)."""
    from backend.reports.export import to_csv, to_json, work_orders
    s = _run(run_id).agent.s
    rows = work_orders(s, _plan_start(plan_start))
    body, media = (to_csv(rows), "text/csv") if fmt == "csv" else (to_json(rows, s), "application/json")
    return Response(body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="walkdown-{s.clip.asset.asset_id}-work-orders.{fmt}"'})


@app.get("/health")
def health() -> dict:
    return dict(ok=True, clips_dir=str(CLIPS_DIR), runs=len(RUNS))
