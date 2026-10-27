import type { Plan } from "@/lib/types";

/** Solver status and gap, always shown. FEASIBLE is never presented as optimal. */
export function StatusBadge({ plan }: { plan: Plan }) {
  const { status, gap, wall_time_s, fallback, stages } = plan.stats;
  const tone = status === "OPTIMAL" ? "ok" : status === "FEASIBLE" ? "warn" : "bad";
  const gapText = gap == null ? "gap n/a" : `gap ${(gap * 100).toFixed(1)}%`;
  return (
    <span className="row">
      <span className={`badge ${tone}`} title={status === "FEASIBLE" ? "A valid plan, not proven optimal within the time limit" : undefined}>
        {status === "OPTIMAL" ? "Optimal" : status === "FEASIBLE" ? "Feasible (not proven optimal)" : status}
      </span>
      <span className="muted mono">
        {gapText} · {wall_time_s.toFixed(1)} s{stages.length ? ` · ${stages.map((s) => `${s.stage}: ${s.status}`).join(", ")}` : ""}
        {fallback ? ` · fallback: ${fallback}` : ""}
      </span>
    </span>
  );
}
