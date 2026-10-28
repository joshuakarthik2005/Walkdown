"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentTrail } from "@/components/AgentTrail";
import { ChangePanel } from "@/components/ChangePanel";
import { Copilot } from "@/components/Copilot";
import { Gantt } from "@/components/Gantt";
import { RegisterView } from "@/components/RegisterView";
import { VoiceNotes } from "@/components/VoiceNotes";
import { Attribution, SafetyNotice } from "@/components/SafetyNotice";
import { StatusBadge } from "@/components/StatusBadge";
import { Unscheduled } from "@/components/Unscheduled";
import * as api from "@/lib/api";
import type { FrameInfo, PlanResponse, Register, RunStatus, TraceEvent } from "@/lib/types";
import { usd } from "@/lib/format";

const POLL_MS = 1200;

const SERVICES: [string, string][] = [
  ["", "unknown"],
  ["lpg", "LPG"],
  ["crude", "crude oil"],
  ["hydrogen", "hydrogen"],
  ["hydrocarbon_vapour", "hydrocarbon vapour"],
  ["chemical", "chemical"],
  ["steam", "steam"],
  ["cooling_water", "cooling water"],
  ["fire_water", "fire water"],
  ["air_nitrogen", "air / nitrogen"],
];

const ASSET_TYPES: [string, string][] = [
  ["pipe", "plant piping"],
  ["tank", "storage tank"],
  ["vessel", "pressure vessel"],
  ["valve", "valve / manifold"],
  ["pump", "pump / compressor"],
  ["support", "pipe support / structure"],
  ["railing", "railing / walkway"],
];

export default function Home() {
  const [clipId, setClipId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [asset, setAsset] = useState({ asset_id: "UNIT2-LPG-RACK", asset_type: "pipe", pressurised: true, location: "", service: "lpg" });
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
  const [pollKey, setPollKey] = useState(0); // bumped to (re)start polling after a run or a change

  const running = status?.status === "running";

  const refreshResults = useCallback(async (id: string) => {
    try {
      const [r, f] = await Promise.all([api.getRegister(id), api.getFrames(id)]);
      setRegister(r);
      setFrames(f.frames);
      setPlan(await api.getPlan(id));
    } catch {
      /* no plan until plan_maintenance has run */
    }
  }, []);

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
  }, [runId, pollKey, refreshResults]);

  async function upload() {
    setError(null);
    setUploading(true);
    try {
      setClipId((await api.uploadClip(files, asset)).clip_id);
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
      setPollKey((k) => k + 1);
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
      setPollKey((k) => k + 1);
    } catch (e) {
      setError(String(e));
    }
  }

  const answers = status?.answers ?? [];
  const latest = answers[answers.length - 1];

  return (
    <main className="shell">
      <header className="top sticky">
        <div>
          <h1>Walkdown</h1>
          <div className="tag">An agent that turns a plant walkdown video into verified defects and a risk-optimal repair plan</div>
        </div>
        <div className="row">
          {plan ? <StatusBadge plan={plan.plan} /> : <span className="badge">no plan yet</span>}
          {status && <span className="muted mono">{usd(status.usd)} · {status.elapsed_s.toFixed(0)} s</span>}
        </div>
      </header>

      <SafetyNotice />

      {error && <div className="panel error-box">{error}</div>}

      <div className="hero">
        <section className="panel">
          <h2>The agent{running ? " · working" : runId ? " · done" : ""}</h2>
          {events.length ? (
            <AgentTrail events={events} running={running} />
          ) : (
            <p className="muted">
              Upload a walkdown clip and run the agent. It decides what to inspect, checks every finding, writes the defect register, plans the
              repairs and explains each decision. Every step appears here as it happens.
            </p>
          )}
          {latest && (
            <>
              <h2 style={{ marginTop: 16 }}>What the agent concluded{answers.length > 1 ? ` · after change ${answers.length - 1}` : ""}</h2>
              <div className="answer answer-big">{latest}</div>
            </>
          )}
        </section>

        <aside>
          <div className="panel">
            <h2>Walkdown clip</h2>
            <label>Video (MP4/MOV) or photos</label>
            <input type="file" multiple accept="video/mp4,video/quicktime,image/jpeg,image/png" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
            <label>Asset id</label>
            <input value={asset.asset_id} onChange={(e) => setAsset({ ...asset, asset_id: e.target.value })} />
            <div className="row">
              <div style={{ flex: 1 }}>
                <label>Asset</label>
                <select value={asset.asset_type} onChange={(e) => setAsset({ ...asset, asset_type: e.target.value })}>
                  {ASSET_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label>Line service</label>
                <select value={asset.service} onChange={(e) => setAsset({ ...asset, service: e.target.value })}>
                  {SERVICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
            </div>
            <label className="row"><input type="checkbox" checked={asset.pressurised} onChange={(e) => setAsset({ ...asset, pressurised: e.target.checked })} /> pressurised</label>
            <label>Location</label>
            <input value={asset.location} onChange={(e) => setAsset({ ...asset, location: e.target.value })} placeholder="e.g. unit 2, east pipe rack" />
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={upload} disabled={!files.length || uploading}>{uploading ? "Uploading…" : "Upload"}</button>
              <input style={{ flex: 1 }} value={clipId} onChange={(e) => setClipId(e.target.value)} placeholder="or paste a clip id" />
            </div>
            <label className="row"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> live (skip cached perception and verification)</label>
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={run} disabled={!clipId || running}>Run the agent</button>
            </div>
          </div>

          {plan && (
            <div className="panel">
              <h2>Something changed on site?</h2>
              <ChangePanel scenario={plan.scenario} nowHour={plan.plan.now} busy={running} onSubmit={change} />
            </div>
          )}

          {plan && runId && (
            <div className="panel">
              <h2>Ask about the register or plan</h2>
              <Copilot runId={runId} busy={running} />
            </div>
          )}
        </aside>
      </div>

      {register && runId && (
        <section className="panel">
          <h2>
            Verified defect register · {register.asset.asset_id}
            {register.asset.service ? ` · ${register.asset.service.replaceAll("_", " ")} service` : ""} · {register.entries.length} defects
          </h2>
          <RegisterView runId={runId} register={register} frames={frames} />
          <VoiceNotes runId={runId} notes={register.voice_notes ?? []} onAdded={() => refreshResults(runId)} />
          <div className="row exports">
            <a href={`${api.API_URL}/runs/${runId}/report.pdf`}>Inspection report (PDF)</a>
            <a href={`${api.API_URL}/runs/${runId}/work_orders.csv`}>Work orders (CSV)</a>
            <a href={`${api.API_URL}/runs/${runId}/work_orders.json`}>Work orders (JSON)</a>
            <span className="muted">CMMS-compatible format, not a certified integration · approval required</span>
          </div>
        </section>
      )}

      {plan && (
        <section className="panel">
          <h2>Repair plan the agent produced</h2>
          <div className="row" style={{ marginBottom: 10 }}>
            <StatusBadge plan={plan.plan} />
            <span className="muted">
              {plan.plan.assignments.length} jobs scheduled · {plan.plan.unscheduled.length} unscheduled · {plan.plan.moved_jobs.length} moved by the last replan
            </span>
          </div>
          <Gantt data={plan} />
          <h2 style={{ marginTop: 14 }}>Walkdown defects that do not fit</h2>
          <Unscheduled explanations={plan.plan.explanations} walkdownIds={plan.walkdown_defect_ids} />
        </section>
      )}

      <p className="scope">
        For plant and facility walkdowns: refineries, tank farms, terminals, pump and compressor stations, power plants. Long cross-country
        pipelines are inspected with in-line inspection tools; Walkdown complements them on unpiggable plant piping. Footage today is handheld;
        drone and robot footage is future work.
      </p>
      <footer className="footer">
        <Attribution /> · Decision support only: every maintenance action needs human approval · Hosted models via the Meta Model API
      </footer>
    </main>
  );
}
