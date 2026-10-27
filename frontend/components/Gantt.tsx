import type { PlanResponse } from "@/lib/types";
import { hourLabel, SEVERITY_COLOUR } from "@/lib/format";

const ROW_H = 34;
const LEFT = 90;
const PX_PER_H = 3.2;

/** Repair schedule per crew. Walkdown defects are coloured by severity; backlog jobs are grey. */
export function Gantt({ data }: { data: PlanResponse }) {
  const { plan, scenario, walkdown_defect_ids } = data;
  const horizon = scenario.horizon_days * 24;
  const width = LEFT + horizon * PX_PER_H + 10;
  const height = 24 + scenario.crews.length * ROW_H + 6;
  const walkdown = new Set(walkdown_defect_ids);
  const moved = new Set(plan.moved_jobs);
  const sev = Object.fromEntries(scenario.defects.map((d) => [d.id, d.severity]));
  const x = (h: number) => LEFT + h * PX_PER_H;
  return (
    <div className="gantt-wrap">
      <svg width={width} height={height} role="img" aria-label="Maintenance schedule by crew">
        {Array.from({ length: scenario.horizon_days + 1 }, (_, d) => (
          <g key={d}>
            <line x1={x(d * 24)} x2={x(d * 24)} y1={18} y2={height} stroke="var(--line)" />
            {d < scenario.horizon_days && (
              <text x={x(d * 24) + 3} y={12} fill="var(--muted)" fontSize={10}>D{d}</text>
            )}
          </g>
        ))}
        {scenario.windows.map((w) => (
          <g key={w.id}>
            <rect x={x(w.start)} y={18} width={(w.end - w.start) * PX_PER_H} height={height - 18} fill="var(--accent)" opacity={0.08} />
            <text x={x(w.start) + 3} y={height - 4} fill="var(--accent)" fontSize={10}>{w.id} shutdown</text>
          </g>
        ))}
        {scenario.crews.map((c, i) => {
          const y = 22 + i * ROW_H;
          return (
            <g key={c.id}>
              <text x={6} y={y + 18} fill="var(--text)" fontSize={12}>{c.id}</text>
              <text x={6} y={y + 30} fill="var(--muted)" fontSize={9}>{c.skills.join(", ").slice(0, 16)}</text>
              {c.unavailable.map((u, k) => (
                <rect key={k} x={x(u.start)} y={y + 2} width={(u.end - u.start) * PX_PER_H} height={ROW_H - 6} fill="var(--bad)" opacity={0.18}>
                  <title>{`${c.id} unavailable ${hourLabel(u.start)} – ${hourLabel(u.end)}`}</title>
                </rect>
              ))}
              {plan.assignments
                .filter((a) => a.crew_id === c.id)
                .map((a) => {
                  const isNew = walkdown.has(a.defect_id);
                  return (
                    <g key={a.defect_id}>
                      <rect
                        x={x(a.start)}
                        y={y + 5}
                        width={Math.max(2, (a.end - a.start) * PX_PER_H)}
                        height={ROW_H - 12}
                        rx={3}
                        fill={isNew ? SEVERITY_COLOUR[sev[a.defect_id] ?? 2] : "var(--backlog)"}
                        stroke={moved.has(a.defect_id) ? "#fff" : "none"}
                        strokeDasharray={moved.has(a.defect_id) ? "3 2" : undefined}
                      >
                        <title>{`${a.defect_id} · ${c.id} · ${hourLabel(a.start)} – ${hourLabel(a.end)}${moved.has(a.defect_id) ? " · moved by replan" : ""}`}</title>
                      </rect>
                      {(a.end - a.start) * PX_PER_H > 26 && (
                        <text x={x(a.start) + 3} y={y + 21} fontSize={9} fill="#111">{a.defect_id}</text>
                      )}
                    </g>
                  );
                })}
            </g>
          );
        })}
        <line x1={x(plan.now)} x2={x(plan.now)} y1={16} y2={height} stroke="var(--ok)" strokeWidth={2} />
        <text x={x(plan.now) + 3} y={22} fill="var(--ok)" fontSize={10}>now</text>
      </svg>
      <div className="legend">
        <span><i style={{ background: "var(--sev2)" }} />walkdown defect (colour = severity)</span>
        <span><i style={{ background: "var(--backlog)" }} />existing backlog</span>
        <span><i style={{ border: "1px dashed #fff" }} />moved by replan</span>
        <span><i style={{ background: "var(--bad)", opacity: 0.4 }} />crew unavailable</span>
        <span><i style={{ background: "var(--accent)", opacity: 0.3 }} />shutdown window</span>
      </div>
    </div>
  );
}
