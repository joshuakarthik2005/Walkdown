"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentTrail } from "@/components/AgentTrail";
import { ChangePanel } from "@/components/ChangePanel";
import { Copilot } from "@/components/Copilot";
import { DropZone } from "@/components/DropZone";
import { ForJudges } from "@/components/ForJudges";
import { Gantt } from "@/components/Gantt";
import { HeadlineMetric } from "@/components/HeadlineMetric";
import { Logo } from "@/components/Logo";
import { PlanApproval } from "@/components/PlanApproval";
import { PlanViews } from "@/components/PlanViews";
import { SampleGallery } from "@/components/SampleGallery";
import { SensitivityPicker } from "@/components/SensitivityPicker";
import { RegisterView } from "@/components/RegisterView";
import { VoiceNotes } from "@/components/VoiceNotes";
import { Attribution, SafetyNotice } from "@/components/SafetyNotice";
import { StatusBadge } from "@/components/StatusBadge";
import { Unscheduled } from "@/components/Unscheduled";
import * as api from "@/lib/api";
import type { FrameInfo, PlanResponse, PlanView, Register, RunStatus, TraceEvent } from "@/lib/types";
import { usd } from "@/lib/format";

const POLL_MS = 1200;
const POLL_MAX_MS = 15000;
const GIVE_UP_MS = 120000; // polling stops after this long without reaching the server
const WAKE_MAX_MS = 180000; // how long the first connection keeps retrying (a sleeping free server takes ~1 min, more under load)
const WAKE_HINT_MS = 2500; // a request still pending after this long is most likely a sleeping server spinning up

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

const label = (pairs: [string, string][], v: string | null) => pairs.find(([k]) => k === (v ?? ""))?.[1] ?? v ?? "";

type Server = "connecting" | "waking" | "ok" | "down";
type Params = { run?: string; sample?: string; example?: string };

/** Keep the address bar shareable: ?run=, ?sample=, ?example= (no reload). */
function setUrl(p: Params) {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => v && q.set(k, v));
  const s = q.toString();
  window.history.replaceState(null, "", s ? `?${s}` : window.location.pathname);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function Home() {
  const [server, setServer] = useState<Server>("connecting");
  const [config, setConfig] = useState<api.ServerConfig | null>(null);
  const [samples, setSamples] = useState<api.Sample[]>([]);
  const [examples, setExamples] = useState<api.Example[]>([]);
  const [sensitivityOptions, setSensitivityOptions] = useState<Awaited<ReturnType<typeof api.getSensitivity>>["options"] | null>(null);

  const [sampleId, setSampleId] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [asset, setAsset] = useState({ asset_id: "UNIT2-LPG-RACK", asset_type: "pipe", pressurised: true, location: "", service: "lpg" });
  const [live, setLive] = useState(false);
  const [mode, setMode] = useState<api.Mode>("cloud");
  const [sensitivity, setSensitivity] = useState<api.Sensitivity>("high_recall");

  const [runId, setRunId] = useState<string | null>(null);
  const [runLabel, setRunLabel] = useState<string>("");
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [register, setRegister] = useState<Register | null>(null);
  const [frames, setFrames] = useState<FrameInfo[]>([]);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const planView = useRef<PlanView | undefined>(undefined); // undefined = the plan the agent uses
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopped, setStopped] = useState(false); // polling gave up: the server is unreachable
  const cursor = useRef(0);
  const [pollKey, setPollKey] = useState(0); // bumped to (re)start polling after a run or a change

  const running = status?.status === "running";
  const busy = running || starting;
  const demo = !!config?.demo_mode;
  const sample = samples.find((s) => s.id === sampleId) ?? null;
  const uploadMode = !sample && files.length > 0;

  // withPlan=false while the agent has only built the register: the plan does not exist yet (the API would answer 409).
  const refreshResults = useCallback(async (id: string, withPlan = true) => {
    try {
      const [r, f] = await Promise.all([api.getRegister(id), api.getFrames(id)]);
      setRegister(r);
      setFrames(f.frames);
      if (withPlan) setPlan(await api.getPlan(id, planView.current));
    } catch {
      /* no plan until plan_maintenance has run */
    }
  }, []);

  const clearResults = () => {
    setError(null);
    setNotice(null);
    setEvents([]);
    setRegister(null);
    setPlan(null);
    setFrames([]);
    setStatus(null);
    setStopped(false);
    planView.current = undefined;
    cursor.current = 0;
  };

  const follow = (id: string, labelText: string) => {
    setRunId(id);
    setRunLabel(labelText);
    setPollKey((k) => k + 1);
  };

  const openExample = useCallback(async (id: string, fallbackNote?: string) => {
    clearResults();
    setStarting(true);
    try {
      const r = await api.openExample(id);
      setSampleId(r.sample);
      setFiles([]);
      follow(r.run_id, `Finished example · ${r.title}`);
      setUrl({ run: r.run_id, example: id });
      if (fallbackNote) setNotice(fallbackNote);
    } catch (e) {
      setError(api.message(e));
    } finally {
      setStarting(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // First load: reach the server (waking it if it sleeps), then restore the state in the URL.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const t0 = Date.now();
      // A sleeping host holds the first request open while it starts, so say so instead of showing nothing.
      const hint = setTimeout(() => !cancelled && setServer((v) => (v === "connecting" ? "waking" : v)), WAKE_HINT_MS);
      let cfg: api.ServerConfig | null = null;
      for (let delay = 1000; !cancelled; delay = Math.min(delay * 2, 10000)) {
        try {
          cfg = await api.getConfig();
          break;
        } catch {
          if (Date.now() - t0 > WAKE_MAX_MS) break;
          setServer("waking");
          await sleep(delay);
        }
      }
      clearTimeout(hint);
      if (cancelled) return;
      if (!cfg) {
        setServer("down");
        return;
      }
      setConfig(cfg);
      setServer("ok");
      const [s, ex] = await Promise.all([api.getSamples().catch(() => ({ samples: [] })), api.getExamples().catch(() => ({ examples: [] }))]);
      api.getSensitivity().then((r) => setSensitivityOptions(r.options)).catch(() => setSensitivityOptions(null));
      if (cancelled) return;
      setSamples(s.samples);
      setExamples(ex.examples);

      const q = new URLSearchParams(window.location.search);
      const run = q.get("run");
      const example = q.get("example");
      const smp = q.get("sample");
      if (smp && s.samples.some((x) => x.id === smp)) setSampleId(smp);
      else if (!example && !run && s.samples.length) setSampleId(s.samples[0].id);
      if (run) {
        try {
          const st = await api.getStatus(run);
          if (st.clip_id && s.samples.some((x) => x.id === st.clip_id)) setSampleId(st.clip_id);
          const ex1 = st.example ? ex.examples.find((e) => e.id === st.example) : null;
          follow(run, ex1 ? `Finished example · ${ex1.title}` : st.clip_id);
          return;
        } catch {
          if (example) {
            void openExample(example, "That run is no longer on the server (runs are kept in memory), so a fresh copy of the example was opened.");
            return;
          }
          setNotice("That run is no longer on the server (runs are kept in memory). Run the sample again or open a finished example.");
          setUrl({ sample: smp ?? undefined });
          return;
        }
      }
      if (example) void openExample(example);
    })();
    return () => {
      cancelled = true;
    };
  }, [openExample]);

  // Poll the run with backoff; stop cleanly when the server stays unreachable.
  useEffect(() => {
    if (!runId) return;
    let stop = false;
    let failures = 0;
    let firstFailure = 0;
    const tick = async () => {
      let delay = POLL_MS;
      try {
        const t = await api.getTrace(runId, cursor.current);
        if (t.events.length) {
          cursor.current = t.next;
          setEvents((prev) => [...prev, ...t.events]);
          const tools = t.events.filter((e) => e.kind === "tool").map((e) => e.name);
          if (tools.some((n) => ["build_register", "plan_maintenance", "replan"].includes(n)))
            void refreshResults(runId, tools.some((n) => n === "plan_maintenance" || n === "replan"));
        }
        const s = await api.getStatus(runId);
        failures = 0;
        setError(null);
        setStatus(s);
        if (s.status !== "running") {
          await refreshResults(runId);
          if (s.status === "error" && s.error) setError(s.error);
          return;
        }
      } catch (e) {
        if (e instanceof api.ApiError && e.status === 404) {
          setError(e.message);
          setStatus((s) => (s ? { ...s, status: "error" } : s));
          return;
        }
        failures += 1;
        if (failures === 1) firstFailure = Date.now();
        if (Date.now() - firstFailure > GIVE_UP_MS) {
          setStopped(true);
          setError(null);
          return;
        }
        setError(api.message(e));
        delay = Math.min(POLL_MS * 2 ** failures, POLL_MAX_MS);
      }
      if (!stop) setTimeout(tick, delay);
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [runId, pollKey, refreshResults]);

  function pickSample(id: string) {
    setSampleId(id);
    setFiles([]);
    setLive(false);
    if (!runId) setUrl({ sample: id });
  }

  function pickFiles(f: File[]) {
    // Checked here too: the server refuses an oversized body before reading it, which browsers can report as a
    // network failure rather than the 413.
    const maxMb = config?.max_upload_mb ?? 500;
    const tooBig = f.find((x) => x.size > maxMb * 1024 * 1024);
    if (tooBig) {
      setError(`${tooBig.name} is ${Math.round(tooBig.size / 1048576)} MB: the limit is ${maxMb} MB.`);
      return;
    }
    setError(null);
    setFiles(f);
    if (f.length) setSampleId(null);
  }

  async function run() {
    clearResults();
    setStarting(true);
    try {
      let clipId = sample?.id ?? "";
      let labelText = sample ? sample.title : "";
      if (uploadMode) {
        const up = await api.uploadClip(files, asset);
        clipId = up.clip_id;
        labelText = `${asset.asset_id} (your upload)`;
      }
      if (!clipId) throw new api.ApiError("Pick a sample walkdown or upload a clip first.", 400);
      const r = await api.startRun(clipId, live, mode, sensitivity);
      follow(r.run_id, labelText);
      setUrl({ run: r.run_id, sample: sample?.id });
    } catch (e) {
      setError(api.message(e));
    } finally {
      setStarting(false);
    }
  }

  async function change(c: Record<string, unknown>, now: number, epsilon: number) {
    if (!runId) return;
    setError(null);
    try {
      await api.postChange(runId, c, now, epsilon);
      setStatus((s) => (s ? { ...s, status: "running" } : s));
      setStopped(false);
      setPollKey((k) => k + 1);
    } catch (e) {
      setError(api.message(e));
    }
  }

  function newWalkdown() {
    clearResults();
    setRunId(null);
    setRunLabel("");
    setUrl({ sample: sampleId ?? undefined });
  }

  const answers = status?.answers ?? [];
  const latest = answers[answers.length - 1];
  const onpremBlocked = demo && mode === "onprem" && !!config && !config.onprem_runs;
  const budgetGone = demo && config?.budget_available === false;
  const canRun = server === "ok" && !busy && !onpremBlocked && (!!sample || uploadMode) && !(budgetGone && uploadMode);
  const exampleForSample = sample ? examples.find((e) => e.id === sample.example) : undefined;

  return (
    <main className="shell">
      <header className="top sticky">
        <div className="brand">
          <Logo />
          <div>
            <h1>Walkdown</h1>
            <div className="tag">An agent that turns a plant walkdown video into verified defects and a risk-optimal repair plan</div>
          </div>
        </div>
        <div className="row">
          {plan ? <StatusBadge plan={plan.plan} /> : <span className="badge">{busy ? "Working…" : "Idle: run the agent to build a plan"}</span>}
          {status && !status.example && (
            <span className="muted mono">
              {usd(status.usd)} · {status.elapsed_s.toFixed(0)} s
            </span>
          )}
        </div>
      </header>

      <SafetyNotice />
      <HeadlineMetric options={sensitivityOptions} />

      {server === "waking" && (
        <div className="panel info-box">
          <span className="spinner" /> Waking up the demo server (~1 min)… The free host sleeps after 15 minutes without visitors.
        </div>
      )}
      {server === "down" && (
        <div className="panel error-box">
          The Walkdown server is not reachable right now. If you run it yourself, start the API (see the README), then reload this page.
        </div>
      )}
      {notice && <div className="panel info-box">{notice}</div>}
      {error && <div className="panel error-box">{error}</div>}
      {stopped && (
        <div className="panel error-box row">
          <span>Stopped: lost contact with the Walkdown server for two minutes.</span>
          <button className="ghost" onClick={() => { setStopped(false); setPollKey((k) => k + 1); }}>Retry</button>
        </div>
      )}

      <div className="hero">
        {runId ? (
          <section className="panel">
            <h2>
              The agent{running ? " · working" : status?.status === "error" ? " · stopped" : status ? " · done" : ""}
              {runLabel ? <span className="h2-sub"> · {runLabel}</span> : null}
            </h2>
            {status?.example && (
              <p className="muted small">
                A finished run loaded from disk: the trail below is the agent&apos;s recorded run. Replans and copilot questions run live.
              </p>
            )}
            {events.length ? (
              <AgentTrail events={events} running={running} />
            ) : (
              <p className="muted">{busy ? "Starting…" : "Waiting for the first step…"}</p>
            )}
            {latest && (
              <>
                <h2 style={{ marginTop: 16 }}>What the agent concluded{answers.length > 1 ? ` · after change ${answers.length - 1}` : ""}</h2>
                <div className="answer answer-big">{latest}</div>
              </>
            )}
          </section>
        ) : (
          <section className="panel">
            <h2>Try a sample walkdown</h2>
            {samples.length ? (
              <SampleGallery samples={samples} examples={examples} selected={sampleId} busy={busy} onSelect={pickSample} onOpenExample={(id) => void openExample(id)} />
            ) : (
              <p className="muted">{server === "ok" ? "No sample walkdowns on this server." : "Loading samples…"}</p>
            )}
            <DropZone files={files} maxMb={config?.max_upload_mb ?? null} maxSeconds={config?.max_duration_s ?? null} busy={busy} onFiles={pickFiles} />
            {uploadMode && (
              <div className="asset-form">
                <div className="row">
                  <div className="grow">
                    <label>Asset id</label>
                    <input value={asset.asset_id} onChange={(e) => setAsset({ ...asset, asset_id: e.target.value })} />
                  </div>
                  <div className="grow">
                    <label>Location</label>
                    <input value={asset.location} onChange={(e) => setAsset({ ...asset, location: e.target.value })} placeholder="e.g. unit 2, east pipe rack" />
                  </div>
                </div>
                <div className="row">
                  <div className="grow">
                    <label>Asset</label>
                    <select value={asset.asset_type} onChange={(e) => setAsset({ ...asset, asset_type: e.target.value })}>
                      {ASSET_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                  <div className="grow">
                    <label>Line service</label>
                    <select value={asset.service} onChange={(e) => setAsset({ ...asset, service: e.target.value })}>
                      {SERVICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                </div>
                <label className="row"><input type="checkbox" checked={asset.pressurised} onChange={(e) => setAsset({ ...asset, pressurised: e.target.checked })} /> pressurised</label>
              </div>
            )}
          </section>
        )}

        <aside>
          <div className="panel run-panel">
            <h2>{runId ? "Walkdown" : "Run"}</h2>
            <div className="selection">
              {sample ? (
                <>
                  <b>{sample.title}</b>
                  <div className="muted small">
                    {sample.asset.asset_id} · {label(ASSET_TYPES, sample.asset.asset_type)}
                    {sample.asset.service ? ` · ${label(SERVICES, sample.asset.service)} service` : ""}
                    {sample.asset.pressurised ? " · pressurised" : ""} · stock demonstration footage
                  </div>
                </>
              ) : uploadMode ? (
                <>
                  <b>Your upload</b>
                  <div className="muted small">{files.length === 1 ? files[0].name : `${files.length} photos`} · fresh inference</div>
                </>
              ) : (
                <span className="muted">Pick a sample walkdown or upload a clip.</span>
              )}
            </div>

            <div className="segmented" role="radiogroup" aria-label="Model mode">
              <button role="radio" aria-checked={mode === "cloud"} className={mode === "cloud" ? "on" : ""} onClick={() => setMode("cloud")} disabled={busy}>Cloud</button>
              <button role="radio" aria-checked={mode === "onprem"} className={mode === "onprem" ? "on" : ""} onClick={() => setMode("onprem")} disabled={busy}>On-prem</button>
            </div>
            <div className="muted mode-note">
              {mode === "cloud"
                ? "Hosted Meta models: SAM 3.1, Muse Spark (agent, verifier), Muse Wonder (second opinion on severe or uncertain grades; disagreements go to a person)."
                : "Open weights only: SAM 3.1 open weights on a scale-to-zero GPU (Modal), box proposals, agent and verifier on Muse Spark Open (Baseten). Built with Muse Spark Open. No Muse Wonder second opinion."}
              {onpremBlocked && (
                <div className="note-strong">
                  On-prem runs are switched off in the public demo: they need the scale-to-zero GPU and the Baseten deployment. Open a finished
                  example to see a complete Cloud run; On-prem&apos;s measured numbers are in the benchmark results.
                </div>
              )}
            </div>
            <SensitivityPicker options={sensitivityOptions} mode={mode} value={sensitivity} busy={busy} onChange={setSensitivity} />

            {!uploadMode && (
              <label className="row small fresh">
                <input type="checkbox" checked={live && !demo} disabled={demo || busy} onChange={(e) => setLive(e.target.checked)} /> Run fresh inference (slower, uses credits)
              </label>
            )}
            <div className="muted small">
              {uploadMode
                ? "Uploads always run fresh inference."
                : demo
                  ? "Samples use cached perception and verification results in the public demo (both sensitivity settings)."
                  : "Samples use cached perception and verification results unless you tick fresh inference."}
              {budgetGone ? " Today's demo budget is used up: finished examples and cached samples still work." : ""}
            </div>

            <div className="run-actions">
              <button className="primary" onClick={run} disabled={!canRun}>
                {starting ? "Starting…" : running ? "Agent working…" : "Run the agent"}
              </button>
              {exampleForSample && (
                <button className="linkish" onClick={() => void openExample(exampleForSample.id)} disabled={busy}>
                  or open the finished example (instant)
                </button>
              )}
            </div>
            {runId && (
              <button className="ghost small-btn" onClick={newWalkdown} disabled={busy}>
                Choose another walkdown
              </button>
            )}
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

          {!runId && <ForJudges demoMode={demo} />}
        </aside>
      </div>

      {register && runId && (
        <section className="panel">
          <h2>
            Verified defect register · {register.asset.asset_id}
            {register.asset.service ? ` · ${register.asset.service.replaceAll("_", " ")} service` : ""} · {register.entries.length} defects
          </h2>
          <RegisterView
            runId={runId}
            register={register}
            frames={frames}
            busy={running}
            onDecide={async (id, decision, severity, source) => {
              try {
                await api.postReview(runId, id, decision, severity, source);
                await refreshResults(runId);
              } catch (e) {
                setError(api.message(e));
              }
            }}
          />
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
          {plan.review && runId && (
            <PlanApproval
              review={plan.review}
              busy={running}
              onApprove={async () => {
                try {
                  await api.approvePlan(runId);
                  await refreshResults(runId);
                } catch (e) {
                  setError(api.message(e));
                }
              }}
            />
          )}
          {plan.comparison && runId && (
            <PlanViews
              comparison={plan.comparison}
              view={plan.view}
              busy={running}
              onSelect={async (v) => {
                planView.current = v;
                try {
                  setPlan(await api.getPlan(runId, v));
                } catch (e) {
                  setError(api.message(e));
                }
              }}
            />
          )}
          <Gantt data={plan} />
          <h2 style={{ marginTop: 14 }}>Walkdown defects that do not fit</h2>
          <Unscheduled explanations={plan.plan.explanations} walkdownIds={plan.walkdown_defect_ids} />
        </section>
      )}

      <p className="scope">
        For plant and facility walkdowns: refineries, tank farms, terminals, pump and compressor stations, power plants. Long cross-country
        pipelines are inspected with in-line inspection tools; Walkdown complements them on unpiggable plant piping. Footage today is handheld;
        drone and robot footage is future work. Sample walkdowns are stock demonstration footage from Pexels, credited on each card.
      </p>
      <footer className="footer">
        <Attribution /> · Decision support only: every maintenance action needs human approval · Hosted models via the Meta Model API
      </footer>
    </main>
  );
}
