"""Walkdown HTTP API (FastAPI).

Endpoints:
  POST /clips                    upload a walkdown video, or photos, plus asset metadata -> clip_id
  POST /runs                     start an agent run on a clip (background thread) -> run_id
  GET  /runs/{id}                status, final answer, cost
  GET  /runs/{id}/trace          structured trace (tool calls with timing and cost); ?since=N for polling
  GET  /runs/{id}/register       verified defect register
  GET  /runs/{id}/plan           current maintenance plan (assignments, stats, explanations)
  POST /runs/{id}/changes        constraint change + epsilon; the agent replans and explains

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
from backend.agent.loop import TraceEvent, WalkdownAgent
from backend.agent.tools import AgentSession
from backend.clients.cost import CostLedger

app = FastAPI(title="Walkdown API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"],
                   allow_headers=["*"])

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
                      pressurised: bool = Form(True), location: str = Form("")) -> dict:
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
        asset = dict(asset_id=asset_id, asset_type=asset_type, pressurised=pressurised, location=location)
        clip = create_clip(clip_id, video=videos[0] if videos else None, photos=None if videos else saved, asset=asset)
    return dict(clip_id=clip_id, duration_s=clip.duration_s, asset=asset)


class RunRequest(BaseModel):
    clip_id: str
    live: bool = Field(False, description="Ignore cached perception/verification results and call the APIs.")
    verify_effort: Literal["minimal", "low", "medium"] = "minimal"
    agent_effort: Literal["minimal", "low", "medium"] = "low"
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
                           verify_effort=req.verify_effort)
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
    return dict(asset=s.clip.asset.__dict__, entries=[dict(
        defect_id=e.defect_id, frames=e.frames, needs_review=e.needs_review,
        grade=e.grade.model_dump(mode="json"),
        detections=[dict(candidate_id=d.candidate_id, frame=d.frame, box=list(d.box), flags=d.flags)
                    for d in e.detections]) for e in s.register])


@app.get("/runs/{run_id}/plan")
def run_plan(run_id: str) -> dict:
    s = _run(run_id).agent.s
    if s.plan is None:
        raise HTTPException(409, "no plan yet")
    return dict(plan=json.loads(s.plan.model_dump_json()), scenario=json.loads(s.scenario.model_dump_json()),
                history=s.plan_history, walkdown_defect_ids=[e.defect_id for e in s.register])


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
    threading.Thread(target=st.turn, args=(message,), daemon=True).start()
    return dict(run_id=run_id, status="running")


SEVERITY_BGR = {1: (120, 200, 120), 2: (60, 200, 230), 3: (40, 160, 255), 4: (40, 90, 255), 5: (60, 40, 230)}


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
    import cv2

    s = _run(run_id).agent.s
    if frame not in s.frame_paths:
        raise HTTPException(404, "unknown frame")
    img = cv2.imread(str(s.frame_paths[frame]), cv2.IMREAD_COLOR)
    for e in s.register:
        for d in e.detections:
            if d.frame != frame:
                continue
            _, inst = s.candidates[d.candidate_id]
            colour = SEVERITY_BGR[d.grade.severity]
            contours, _ = cv2.findContours(inst.mask.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            overlay = img.copy()
            cv2.drawContours(overlay, contours, -1, colour, -1)
            img = cv2.addWeighted(overlay, 0.25, img, 0.75, 0)
            cv2.drawContours(img, contours, -1, colour, 2)
            l, t = d.box[0], max(14, d.box[1] - 4)
            cv2.putText(img, f"{e.defect_id} S{d.grade.severity}", (l, t), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return Response(buf.tobytes(), media_type="image/jpeg")


@app.get("/health")
def health() -> dict:
    return dict(ok=True, clips_dir=str(CLIPS_DIR), runs=len(RUNS))
