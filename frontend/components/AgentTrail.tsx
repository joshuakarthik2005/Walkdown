import type { TraceEvent } from "@/lib/types";
import { usd } from "@/lib/format";

const STEP: Record<string, { title: string; what: string }> = {
  segment_frames: { title: "Looks at the clip", what: "SAM 3.1 segments rust on sampled frames" },
  verify_candidate: { title: "Checks each finding", what: "Muse Spark accepts or rejects and grades severity" },
  build_register: { title: "Writes the defect register", what: "merges repeat sightings into one entry per defect" },
  plan_maintenance: { title: "Plans the repairs", what: "CP-SAT schedules crews, permits and shutdown windows" },
  replan: { title: "Replans after the change", what: "two-stage CP-SAT: lowest risk, then fewest moved jobs" },
  explain_plan: { title: "Reads the planner's reasons", what: "structured reason codes, nothing invented" },
};

// Tools that call a Meta model; the others (register, CP-SAT, explanations) run locally.
const API_TOOLS = new Set(["segment_frames", "verify_candidate"]);

/** The agent's decision flow: each tool call as a step, with what it decided. Model turns are folded in. */
export function AgentTrail({ events, running }: { events: TraceEvent[]; running: boolean }) {
  const total = events.reduce((s, e) => s + e.usd, 0);
  const steps = events.filter((e) => e.kind === "tool" || e.kind === "error");
  const thinking = events.filter((e) => e.kind === "llm");
  const thinkingS = thinking.reduce((s, e) => s + e.duration_s, 0);
  return (
    <div>
      <ol className="flow">
        {steps.map((e) => {
          const s = STEP[e.name];
          const args = e.args as Record<string, unknown>;
          const argText =
            e.name === "segment_frames" && args.fps ? `${args.fps} fps${args.start_s != null ? `, ${args.start_s}–${args.end_s ?? "end"} s` : ""}`
            : e.name === "verify_candidate" && Array.isArray(args.candidate_ids) ? `${args.candidate_ids.length} candidates`
            : e.name === "replan" && args.epsilon != null ? `ε ${args.epsilon}` : "";
          return (
            <li key={e.step} className={e.error ? "step failed" : "step"}>
              <div className="step-head">
                <span className="step-title">{s?.title ?? e.name}</span>
                <span className="meta">
                  {e.duration_s.toFixed(1)} s · {e.usd > 0 ? usd(e.usd) : API_TOOLS.has(e.name) ? "cached" : "local"}
                </span>
              </div>
              <div className="muted small">{s?.what}{argText ? ` · ${argText}` : ""}</div>
              <div className={e.error ? "error-box" : "decision"}>{e.error ? `Tool error, the agent retried: ${e.error.slice(0, 140)}` : e.summary}</div>
            </li>
          );
        })}
        {running && (
          <li className="step pending">
            <span className="spinner" /> <span className="muted">working…</span>
          </li>
        )}
      </ol>
      <div className="muted small" style={{ marginTop: 8 }}>
        {steps.length} tool calls · {thinking.length} Muse Spark turns ({thinkingS.toFixed(0)} s) · {usd(total)} this run
      </div>
    </div>
  );
}
