import type { FrameInfo, Register } from "@/lib/types";
import { frameUrl } from "@/lib/api";
import { SEVERITY_COLOUR } from "@/lib/format";

/** Verified defect register: frames with masks drawn by the backend, plus one row per defect. */
export function RegisterView({ runId, register, frames }: { runId: string; register: Register; frames: FrameInfo[] }) {
  return (
    <div>
      <div className="frames">
        {frames.map((f) => (
          <figure key={f.frame}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={frameUrl(runId, f.frame)} alt={`Frame ${f.frame} with ${f.detections.length} defects outlined`} />
            <figcaption>
              frame {f.frame} · {f.detections.map((d) => d.defect_id).join(", ")}
            </figcaption>
          </figure>
        ))}
      </div>
      <table style={{ marginTop: 10 }}>
        <thead>
          <tr>
            <th>ID</th>
            <th>Sev</th>
            <th>Type</th>
            <th>Evidence</th>
            <th>Action</th>
            <th>Conf.</th>
          </tr>
        </thead>
        <tbody>
          {register.entries.map((e) => (
            <tr key={e.defect_id}>
              <td className="mono">
                {e.defect_id}
                {e.needs_review && <div className="badge warn" title={e.detections.flatMap((d) => d.flags).join(", ")}>review</div>}
              </td>
              <td>
                <span className="sev" style={{ background: SEVERITY_COLOUR[e.grade.severity] }}>{e.grade.severity}</span>
              </td>
              <td>{e.grade.defect_type.replaceAll("_", " ")}</td>
              <td className="muted">
                {e.grade.evidence.visual_cues.slice(0, 2).join("; ")}
                <div>{e.grade.evidence.location}</div>
              </td>
              <td>{e.grade.recommended_action.replaceAll("_", " ")}</td>
              <td className="mono">{e.grade.confidence.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
