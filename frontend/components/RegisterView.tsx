import { useState } from "react";
import type { Decision, FrameInfo, Register, RegisterEntry, SeveritySource } from "@/lib/types";
import { frameUrl } from "@/lib/api";
import { SEVERITY_COLOUR } from "@/lib/format";

// The verifier sees the candidate outlined in cyan and sometimes says so; that detail means nothing here.
const cleanCue = (s: string) => s.replace(/\s*(inside|within) (the )?(cyan )?outline/gi, "").trim();

const OTHER_BUTTONS: { decision: Decision; label: string }[] = [
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
  onDecide: (defectId: string, decision: Decision, severity?: number, source?: SeveritySource) => void;
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
      <table className="register-table" style={{ marginTop: 10 }}>
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
                {e.review && <ReviewCell entry={e} excluded={excluded.has(e.defect_id)} busy={busy} onDecide={onDecide} />}
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

/** A person's review of one entry: the opinions side by side, a severity to approve with, and the decision buttons. */
function ReviewCell({
  entry: e,
  excluded,
  busy,
  onDecide,
}: {
  entry: RegisterEntry;
  excluded: boolean;
  busy: boolean;
  onDecide: (defectId: string, decision: Decision, severity?: number, source?: SeveritySource) => void;
}) {
  const shown = e.review.reviewer_severity ?? e.grade.severity;
  const [sev, setSev] = useState<number>(shown);
  const [source, setSource] = useState<SeveritySource>(e.review.severity_source ?? "verifier");
  const ops = e.opinions ?? [];
  return (
    <>
      <div className={`badge ${TONE[e.review.decision]}`} title={e.review.at ? `decided ${new Date(e.review.at).toLocaleString()}` : "no decision yet"}>
        {e.review.label}
        {e.review.reviewer_severity ? ` · severity ${e.review.reviewer_severity} (${e.review.severity_source})` : ""}
      </div>
      {e.review.decision === "rejected" && (
        <div className="muted small">{excluded ? "excluded from plan" : "leaves the plan at the next replan"}</div>
      )}
      {ops.length > 0 && (
        <div className={`opinions${ops.length > 1 ? " two" : ""}`}>
          {ops.map((o) => (
            <div key={o.source} className="opinion">
              <div className="small">
                <b>{o.source === "verifier" ? "Verifier" : "Second opinion"}</b> <span className="muted">({o.model})</span>
              </div>
              <div className="small">
                {o.is_defect ? "defect" : "not a defect"}
                {o.severity !== null ? ` · severity ${o.severity}` : ""}
              </div>
              <div className="muted small">{cleanCue(o.evidence)}</div>
              {ops.length > 1 && o.severity !== null && (
                <button
                  className="ghost use-this"
                  disabled={busy}
                  onClick={() => {
                    setSev(o.severity as number);
                    setSource(o.source);
                  }}
                >
                  Use this
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="review-btns" role="group" aria-label={`Review ${e.defect_id}`}>
        <label className="sev-pick">
          <span className="sr-only">Severity for {e.defect_id}</span>
          <select
            value={sev}
            disabled={busy}
            onChange={(ev) => {
              setSev(Number(ev.target.value));
              setSource("own value");
            }}
            aria-label={`Severity for ${e.defect_id}`}
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                Severity {n}
              </option>
            ))}
          </select>
        </label>
        <button
          className={e.review.decision === "approved" ? "on" : "ghost"}
          aria-pressed={e.review.decision === "approved"}
          disabled={busy}
          onClick={() => onDecide(e.defect_id, "approved", sev, sev === e.grade.severity && source === "own value" ? "verifier" : source)}
        >
          Approve
        </button>
        {OTHER_BUTTONS.map((b) => (
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
  );
}
