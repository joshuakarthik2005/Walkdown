import type { Explanation } from "@/lib/types";
import { REASON_TEXT } from "@/lib/format";

/** Walkdown defects the plan could not fit, with the planner's own reasons (and crew-hour numbers). */
export function Unscheduled({ explanations, walkdownIds }: { explanations: Explanation[]; walkdownIds: string[] }) {
  const ids = new Set(walkdownIds);
  const rows = explanations.filter((e) => e.status === "unscheduled" && ids.has(e.defect_id));
  if (!rows.length) return <p className="muted">Every walkdown defect is scheduled.</p>;
  return (
    <ul className="reasons" style={{ color: "var(--text)" }}>
      {rows.map((e) => (
        <li key={e.defect_id}>
          <span className="mono">{e.defect_id}</span>:{" "}
          {e.reasons.map((r) => (r.detail && typeof r.detail.summary === "string" ? r.detail.summary : REASON_TEXT[r.code] ?? r.code)).join("; ")}
        </li>
      ))}
    </ul>
  );
}
