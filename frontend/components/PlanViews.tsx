import type { PlanComparison, PlanMetrics, PlanView } from "@/lib/types";

const LABEL: Record<PlanView, string> = { grouped: "Grouped jobs", individual: "Individual defects" };

const pct = (gap: number | null) => (gap == null ? "n/a" : `${(gap * 100).toFixed(1)}%`);

/** Toggle between the grouped (work-package) and individual plan, with the trade-off shown side by side. */
export function PlanViews({
  comparison,
  view,
  busy,
  onSelect,
}: {
  comparison: PlanComparison;
  view: PlanView;
  busy: boolean;
  onSelect: (v: PlanView) => void;
}) {
  const views = (["grouped", "individual"] as PlanView[]).filter((v) => comparison[v]);
  if (views.length < 2) return null;
  const base = comparison.individual.exposure;
  const rows: [string, (m: PlanMetrics) => string][] = [
    ["Solver status", (m) => m.status],
    ["Gap", (m) => pct(m.gap)],
    ["Jobs", (m) => String(m.jobs)],
    ["Risk exposure", (m) => `${m.exposure.toLocaleString()}${m === comparison.individual ? "" : ` (${m.exposure >= base ? "+" : ""}${(((m.exposure - base) / base) * 100).toFixed(1)}%)`}`],
    ["Makespan", (m) => `${m.makespan_h} h`],
    ["Defects unscheduled", (m) => String(m.defects_unscheduled)],
    ["Setup hours saved", (m) => `${m.setup_hours_saved} h`],
  ];
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="row" role="radiogroup" aria-label="Plan view">
        {views.map((v) => (
          <button key={v} role="radio" aria-checked={view === v} className={view === v ? "" : "ghost"} disabled={busy} onClick={() => onSelect(v)}>
            {LABEL[v]}
            {comparison.chosen === v ? " (used)" : ""}
          </button>
        ))}
      </div>
      <p className="muted" style={{ margin: "6px 0" }}>
        The agent uses the {LABEL[comparison.chosen].toLowerCase()} plan: {comparison.reason}. Grouped jobs share setup but every defect in a
        group waits for the whole group, so risk exposure can be higher.
      </p>
      <table>
        <thead>
          <tr>
            <th />
            {views.map((v) => (
              <th key={v}>{LABEL[v]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, f]) => (
            <tr key={name}>
              <td>{name}</td>
              {views.map((v) => (
                <td key={v} className="mono">
                  {f(comparison[v] as PlanMetrics)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
