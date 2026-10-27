import type { TraceEvent } from "@/lib/types";
import { usd } from "@/lib/format";

const LABEL: Record<string, string> = {
  segment_frames: "Segment frames (SAM 3.1)",
  verify_candidate: "Verify candidates (Muse Spark)",
  build_register: "Build defect register",
  plan_maintenance: "Plan maintenance (CP-SAT)",
  replan: "Replan (CP-SAT, two-stage)",
  explain_plan: "Explain plan",
};

/** Live trail of the agent's model turns and tool calls. */
export function AgentTrail({ events, running }: { events: TraceEvent[]; running: boolean }) {
  const total = events.reduce((s, e) => s + e.usd, 0);
  return (
    <div>
      <ul className="trail">
        {events
          .filter((e) => e.kind !== "final")
          .map((e) => (
            <li key={e.step} className={`${e.kind}${e.error ? " has-error" : ""}`}>
              <span className="dot" />
              <span>
                <span className="name">{e.kind === "llm" ? "Muse Spark" : LABEL[e.name] ?? e.name}</span>
                <div className="muted">{e.error ? <span className="error-box">{e.error.slice(0, 160)}</span> : e.summary}</div>
              </span>
              <span className="meta">
                {e.duration_s.toFixed(1)} s
                <br />
                {e.usd > 0 ? usd(e.usd) : "cached"}
              </span>
            </li>
          ))}
      </ul>
      <div className="row muted" style={{ marginTop: 8 }}>
        {running && <span className="spinner" />}
        <span>
          {events.filter((e) => e.kind === "tool").length} tool calls · {usd(total)}
        </span>
      </div>
    </div>
  );
}
