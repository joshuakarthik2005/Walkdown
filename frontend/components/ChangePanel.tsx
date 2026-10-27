"use client";

import { useState } from "react";
import type { Scenario } from "@/lib/types";

type Kind = "crew_unavailable" | "shutdown_window_changed" | "new_defect";

/** Post a constraint change; the agent replans (two-stage) and explains what changed. */
export function ChangePanel({
  scenario,
  nowHour,
  busy,
  onSubmit,
}: {
  scenario: Scenario;
  nowHour: number;
  busy: boolean;
  onSubmit: (change: Record<string, unknown>, now: number, epsilon: number) => void;
}) {
  const [kind, setKind] = useState<Kind>("crew_unavailable");
  const [now, setNow] = useState(Math.max(nowHour, 24));
  const [crew, setCrew] = useState(scenario.crews[0]?.id ?? "");
  const [hours, setHours] = useState(72);
  const [windowId, setWindowId] = useState(scenario.windows[0]?.id ?? "");
  const [cancel, setCancel] = useState(true);
  const [shift, setShift] = useState(48);
  const [epsilon, setEpsilon] = useState(0.02);

  function submit() {
    let change: Record<string, unknown>;
    if (kind === "crew_unavailable") change = { type: kind, crew_id: crew, start: now, end: now + hours };
    else if (kind === "shutdown_window_changed") {
      const w = scenario.windows.find((x) => x.id === windowId);
      change = cancel || !w ? { type: kind, window_id: windowId } : { type: kind, window_id: windowId, new_start: w.start + shift, new_end: w.end + shift };
    } else
      change = {
        type: kind,
        defect: { id: `N${Date.now() % 1000}`, asset: "WALKDOWN-FOLLOW-UP", severity: 5, failure_risk: 0.9, repair_hours: 6, skill: "coating", needs_shutdown: false },
      };
    onSubmit(change, now, epsilon);
  }

  return (
    <div>
      <label>Change</label>
      <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
        <option value="crew_unavailable">Crew becomes unavailable</option>
        <option value="shutdown_window_changed">Shutdown window moved or cancelled</option>
        <option value="new_defect">New critical defect found</option>
      </select>
      <label>Current hour (work started before this stays fixed)</label>
      <input type="number" min={nowHour} value={now} onChange={(e) => setNow(Number(e.target.value))} />
      {kind === "crew_unavailable" && (
        <>
          <label>Crew</label>
          <select value={crew} onChange={(e) => setCrew(e.target.value)}>
            {scenario.crews.map((c) => (
              <option key={c.id} value={c.id}>{c.id} · {c.skills.join(", ")}</option>
            ))}
          </select>
          <label>For how many hours</label>
          <input type="number" min={1} value={hours} onChange={(e) => setHours(Number(e.target.value))} />
        </>
      )}
      {kind === "shutdown_window_changed" && (
        <>
          <label>Window</label>
          <select value={windowId} onChange={(e) => setWindowId(e.target.value)}>
            {scenario.windows.map((w) => (
              <option key={w.id} value={w.id}>{w.id} · hours {w.start}–{w.end}</option>
            ))}
          </select>
          <label className="row"><input type="checkbox" checked={cancel} onChange={(e) => setCancel(e.target.checked)} /> cancel the window</label>
          {!cancel && (
            <>
              <label>Move by (hours)</label>
              <input type="number" value={shift} onChange={(e) => setShift(Number(e.target.value))} />
            </>
          )}
        </>
      )}
      <label>Stability vs risk: ε = {epsilon.toFixed(2)} (risk may rise by up to {(epsilon * 100).toFixed(0)}% to move fewer jobs)</label>
      <input type="range" min={0} max={0.1} step={0.01} value={epsilon} onChange={(e) => setEpsilon(Number(e.target.value))} />
      <div className="row" style={{ marginTop: 10 }}>
        <button onClick={submit} disabled={busy}>Replan</button>
      </div>
    </div>
  );
}
