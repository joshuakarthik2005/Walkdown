"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentTrail } from "@/components/AgentTrail";
import { ChangePanel } from "@/components/ChangePanel";
import { Gantt } from "@/components/Gantt";
import { RegisterView } from "@/components/RegisterView";
import { StatusBadge } from "@/components/StatusBadge";
import { Unscheduled } from "@/components/Unscheduled";
import * as api from "@/lib/api";
import type { FrameInfo, PlanResponse, Register, RunStatus, TraceEvent } from "@/lib/types";
import { usd } from "@/lib/format";

const POLL_MS = 1200;

export default function Home() {
  const [clipId, setClipId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [asset, setAsset] = useState({ asset_id: "PIPE-RACK-207", asset_type: "pipe", pressurised: true, location: "" });
  const [live, setLive] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [register, setRegister] = useState<Register | null>(null);
  const [frames, setFrames] = useState<FrameInfo[]>([]);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const cursor = useRef(0);

  const running = status?.status === "running";

  const refreshResults = useCallback(async (id: string) => {
    try {
      const [r, f] = await Promise.all([api.getRegister(id), api.getFrames(id)]);
      setRegister(r);
      setFrames(f.frames);
      setPlan(await api.getPlan(id));
    } catch {
      /* the plan is not ready until plan_maintenance has run */
    }
  }, []);

  // Poll the trace and status while the agent works.
  useEffect(() => {
    if (!runId) return;
    let stop = false;
    const tick = async () => {
      try {
        const t = await api.getTrace(runId, cursor.current);
        if (t.events.length) {
          cursor.current = t.next;
          setEvents((prev) => [...prev, ...t.events]);
          if (t.events.some((e) => e.kind === "tool" && ["build_register", "plan_maintenance", "replan"].includes(e.name)))
            void refreshResults(runId);
        }
        const s = await api.getStatus(runId);
        setStatus(s);
        if (s.status !== "running") {
          await refreshResults(runId);
          return;
        }
      } catch (e) {
        setError(String(e));
      }
      if (!stop) setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [runId, status?.answers.length, refreshResults]);

  async function upload() {
    setError(null);
    setUploading(true);
    try {
      const r = await api.uploadClip(files, asset);
      setClipId(r.clip_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }

  async function run() {
    setError(null);
    setEvents([]);
    setRegister(null);
    setPlan(null);
    setFrames([]);
    cursor.current = 0;
    try {
      const r = await api.startRun(clipId, live);
      setStatus(null);
      setRunId(r.run_id);
    } catch (e) {
      setError(String(e));
    }
  }

  async function change(c: Record<string, unknown>, now: number, epsilon: number) {
    if (!runId) return;
    setError(null);
    try {
      await api.postChange(runId, c, now, epsilon);
      setStatus((s) => (s ? { ...s, status: "running" } : s));
    } catch (e) {
      setError(String(e));
    }
  }

  const answers = status?.answers ?? [];

  return (
    <main className="shell">
      <header className="top">
        <div>
          <h1>Walkdown</h1>
          <div className="tag">Inspection video → verified defect register → risk-optimal maintenance plan</div>
        </div>
        <div className="row">
          {plan && <StatusBadge plan={plan.plan} />}
          {status && <span className="muted mono">{usd(status.usd)} · {status.elapsed_s.toFixed(0)} s</span>}
        </div>
      </header>

      <div className="grid">
        <section>
          <div className="panel">
            <h2>1 · Walkdown clip</h2>
            <label>Video (MP4/MOV) or photos</label>
            <input type="file" multiple accept="video/mp4,video/quicktime,image/jpeg,image/png" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
            <label>Asset id</label>
            <input value={asset.asset_id} onChange={(e) => setAsset({ ...asset, asset_id: e.target.value })} />
            <div className="row">
              <div style={{ flex: 1 }}>
                <label>Asset type</label>
                <select value={asset.asset_type} onChange={(e) => setAsset({ ...asset, asset_type: e.target.value })}>
                  {["pipe", "tank", "valve", "support", "railing"].map((t) => <option key={t}>{t}</option>)}
                </select>
              </div>
              <label className="row" style={{ marginTop: 24 }}>
                <input type="checkbox" checked={asset.pressurised} onChange={(e) => setAsset({ ...asset, pressurised: e.target.checked })} /> pressurised
              </label>
            </div>
            <label>Location</label>
            <input value={asset.location} onChange={(e) => setAsset({ ...asset, location: e.target.value })} placeholder="e.g. unit 2 east rack" />
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={upload} disabled={!files.length || uploading}>{uploading ? "Uploading…" : "Upload"}</button>
              <span className="muted">or clip id</span>
              <input style={{ flex: 1 }} value={clipId} onChange={(e) => setClipId(e.target.value)} placeholder="clip-…" />
            </div>
            <label className="row"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> live mode (ignore cached perception and verification)</label>
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={run} disabled={!clipId || running}>Run agent</button>
            </div>
          </div>

          <div className="panel">
            <h2>2 · Agent at work</h2>
            {events.length ? <AgentTrail events={events} running={running} /> : <p className="muted">The agent's tool calls appear here as it works.</p>}
          </div>

          {plan && (
            <div className="panel">
              <h2>5 · Change a constraint</h2>
              <ChangePanel scenario={plan.scenario} nowHour={plan.plan.now} busy={running} onSubmit={change} />
            </div>
          )}
        </section>

        <section>
          {error && <div className="panel error-box">{error}</div>}

          {answers.length > 0 && (
            <div className="panel">
              <h2>Agent summary{answers.length > 1 ? ` · update ${answers.length - 1}` : ""}</h2>
              <div className="answer">{answers[answers.length - 1]}</div>
            </div>
          )}

          {register && runId && (
            <div className="panel">
              <h2>3 · Verified defect register · {register.asset.asset_id} · {register.entries.length} defects</h2>
              <RegisterView runId={runId} register={register} frames={frames} />
            </div>
          )}

          {plan && (
            <div className="panel">
              <h2>4 · Maintenance plan</h2>
              <div className="row" style={{ marginBottom: 10 }}>
                <StatusBadge plan={plan.plan} />
                <span className="muted">
                  {plan.plan.assignments.length} jobs scheduled · {plan.plan.unscheduled.length} unscheduled · {plan.plan.moved_jobs.length} moved by last replan
                </span>
              </div>
              <Gantt data={plan} />
              <h2 style={{ marginTop: 14 }}>Not scheduled (walkdown defects)</h2>
              <Unscheduled explanations={plan.plan.explanations} walkdownIds={plan.walkdown_defect_ids} />
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
