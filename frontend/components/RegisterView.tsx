import type { Decision, FrameInfo, Register } from "@/lib/types";
import { frameUrl } from "@/lib/api";
import { SEVERITY_COLOUR } from "@/lib/format";

// The verifier sees the candidate outlined in cyan and sometimes says so; that detail means nothing here.
const cleanCue = (s: string) => s.replace(/\s*(inside|within) (the )?(cyan )?outline/gi, "").trim();

const BUTTONS: { decision: Decision; label: string }[] = [
  { decision: "approved", label: "Approve" },
  { decision: "rejected", label: "Reject" },
  { decision: "reinspect", label: "Needs re-inspection" },
];
const TONE: Record<Decision, string> = { pending: "", approved: "ok", rejected: "bad", reinspect: "warn" };

/** Verified defect register: frames with masks drawn by the backend, plus one row per defect with a person's
 * review decision (Approve / Reject / Needs re-inspection). Nothing is decided automatically. */
export function RegisterView({
  runId,
  register,
  frames,
  busy,
  onDecide,
}: {
  runId: string;
  register: Register;
  frames: FrameInfo[];
  busy: boolean;
  onDecide: (defectId: string, decision: Decision) => void;
}) {
  const rv = register.review;
  const excluded = new Set(rv?.rejected_excluded ?? []);
  return (
    <div>
      {rv && (
        <p className="muted small review-summary">
          <b>Human review:</b> {rv.counts.approved} approved · {rv.counts.rejected} rejected · {rv.counts.reinspect} need
          re-inspection · {rv.counts.pending} pending. Walkdown proposes; a person decides. Rejected entries leave the plan at
          the next replan.
        </p>
      )}
      <div className="frames">
        {frames.map((f) => (
          <figure key={f.frame}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={frameUrl(runId, f.frame)} alt={`Frame ${f.frame} with ${f.detections.length} defects outlined`} />
            <figcaption title={f.detections.map((d) => d.defect_id).join(", ")}>
              frame {f.frame} · {f.detections.length} defect{f.detections.length === 1 ? "" : "s"}
            </figcaption>
          </figure>
        ))}
      </div>
      <div className="table-scroll">
      <table style={{ marginTop: 10 }}>
        <thead>
          <tr>
            <th>ID</th>
            <th>Review</th>
            <th>Job</th>
            <th>Sev</th>
            <th>Type</th>
            <th>Evidence</th>
            <th>Action</th>
            <th>Conf.</th>
          </tr>
        </thead>
        <tbody>
          {register.entries.map((e) => (
            <tr key={e.defect_id} className={e.review?.decision === "rejected" ? "rejected" : undefined}>
              <td className="mono">
                {e.defect_id}
                {e.needs_review && <div className="badge warn" title={e.detections.flatMap((d) => d.flags).join(", ")}>review</div>}
                <SeniorBadge entry={e} />
              </td>
              <td className="review-cell">
                {e.review && (
                  <>
                    <div className={`badge ${TONE[e.review.decision]}`} title={e.review.at ? `decided ${new Date(e.review.at).toLocaleString()}` : "no decision yet"}>
                      {e.review.label}
                    </div>
                    {e.review.decision === "rejected" && (
                      <div className="muted small">{excluded.has(e.defect_id) ? "excluded from plan" : "leaves the plan at the next replan"}</div>
                    )}
                    <div className="review-btns" role="group" aria-label={`Review ${e.defect_id}`}>
                      {BUTTONS.map((b) => (
                        <button
                          key={b.decision}
                          className={e.review.decision === b.decision ? "on" : "ghost"}
                          aria-pressed={e.review.decision === b.decision}
                          disabled={busy || e.review.decision === b.decision}
                          onClick={() => onDecide(e.defect_id, b.decision)}
                        >
                          {b.label}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </td>
              <td className="mono" title={e.package_id && e.package_id !== e.defect_id ? "work package: repaired together with nearby defects in one job" : "own job"}>
                {e.package_id ?? "-"}
              </td>
              <td>
                <span className="sev" style={{ background: SEVERITY_COLOUR[e.grade.severity] }}>{e.grade.severity}</span>
              </td>
              <td>{e.grade.defect_type.replaceAll("_", " ")}</td>
              <td className="muted">
                {e.grade.evidence.visual_cues.slice(0, 2).map(cleanCue).join("; ")}
                <div>{e.grade.evidence.location}</div>
              </td>
              <td>{e.grade.recommended_action.replaceAll("_", " ")}</td>
              <td className="mono">{e.grade.confidence.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function SeniorBadge({ entry }: { entry: Register["entries"][number] }) {
  const reviews = entry.detections.map((d) => d.senior).filter((r): r is NonNullable<typeof r> => r !== null);
  if (!reviews.length) return null;
  const r = reviews[0];
  const what = r.changed_decision ? (r.first_is_defect ? "disputed: needs human review" : "accepted a first-pass rejection") : r.changed_severity ? `severity ${r.first_severity} → ${entry.grade.severity}` : "confirmed";
  return (
    <div className="badge senior" title={`Second opinion from Muse Wonder (${r.reason}): ${what}. A second opinion surfaces disagreements for a person to resolve; it is not a more accurate grade.`}>
      {r.changed_decision && r.first_is_defect ? "disputed: needs human review" : `second opinion${r.changed_decision || r.changed_severity ? " ✎" : ""}`}
    </div>
  );
}
