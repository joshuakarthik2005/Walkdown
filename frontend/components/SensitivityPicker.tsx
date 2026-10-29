import type { Measure, Mode, OperatingPoint, Sensitivity } from "@/lib/api";

const pct = (m: Measure) => `${(m.value * 100).toFixed(1)}%`;
const detail = (m: Measure) => `${m.k}/${m.n}, 95% CI ${(m.ci[0] * 100).toFixed(1)}–${(m.ci[1] * 100).toFixed(1)}%`;

function Point({ p }: { p: OperatingPoint }) {
  return (
    <span className="muted mono" style={{ fontSize: 12 }}>
      recall <b title={`audited real-rust candidates: ${detail(p.recall)}`}>{pct(p.recall)}</b> · clean images flagged{" "}
      <b title={`real clean-pipe images with a false alarm: ${detail(p.false_alarm_images)}`}>{pct(p.false_alarm_images)}</b>
    </span>
  );
}

/** Detection sensitivity with its measured operating points (Cloud); On-prem shows its fixed point. */
export function SensitivityPicker({
  options,
  mode,
  value,
  busy,
  onChange,
}: {
  options: Record<Sensitivity | "on_prem", OperatingPoint> | null;
  mode: Mode;
  value: Sensitivity;
  busy: boolean;
  onChange: (s: Sensitivity) => void;
}) {
  if (!options) return null;
  if (mode === "onprem") {
    const p = options.on_prem;
    return (
      <div className="sensitivity">
        <label>Detection sensitivity</label>
        <div className="muted">
          {p.label}: fixed. <Point p={p} />
        </div>
      </div>
    );
  }
  return (
    <div className="sensitivity" role="radiogroup" aria-label="Detection sensitivity">
      <label>Detection sensitivity</label>
      {(["high_recall", "balanced"] as Sensitivity[]).map((k) => {
        const p = options[k];
        return (
          <label key={k} className="row" style={{ alignItems: "baseline" }} title={p.note}>
            <input type="radio" name="sensitivity" checked={value === k} disabled={busy} onChange={() => onChange(k)} />
            <span>
              {p.label}
              {p.default ? " (default)" : ""}
            </span>
            <Point p={p} />
          </label>
        );
      })}
      <div className="muted" style={{ fontSize: 12 }}>
        A missed defect is the dangerous error and every flag is reviewed by a person, so the default favours recall. Measured on the
        builder&apos;s blind audit (113 real-rust candidates) and 191 real clean-pipe images.
      </div>
    </div>
  );
}
