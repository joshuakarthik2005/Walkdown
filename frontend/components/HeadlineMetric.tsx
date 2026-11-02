import type { OperatingPoint, Sensitivity } from "@/lib/api";

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

/** One headline number (audited recall per sensitivity setting); the other measures are one click away. */
export function HeadlineMetric({ options }: { options: Record<Sensitivity | "on_prem", OperatingPoint> | null }) {
  if (!options) return null;
  const hr = options.high_recall;
  const bal = options.balanced;
  return (
    <details className="headline">
      <summary>
        <span className="headline-label">Audited recall</span>
        <span className="headline-value">{pct(hr.recall.value)}</span>
        <span className="muted">High recall (default)</span>
        <span className="headline-sep">·</span>
        <span className="headline-value small-value">{pct(bal.recall.value)}</span>
        <span className="muted">Balanced</span>
        <span className="link">What these numbers mean</span>
      </summary>
      <div className="headline-body">
        <p>
          <b>Audited recall</b> is the share of real rust the agent keeps after verification, on the builder&apos;s blind audit of{" "}
          {hr.recall.n} real-rust candidates. The cost of that recall is false alarms: High recall flags{" "}
          {pct(hr.false_alarm_images.value)} of {hr.false_alarm_images.n} real clean-pipe images, Balanced {pct(bal.false_alarm_images.value)}.
          Every flag goes to a person.
        </p>
        <p>On the held-out test set, the default pipeline&apos;s detections measure three different things:</p>
        <ul>
          <li>
            <b>Image detection 98%</b>: on images that have corrosion, it finds corrosion somewhere.
          </li>
          <li>
            <b>Area coverage 84%</b>: of the annotated corroded area, how much its masks cover.
          </li>
          <li>
            <b>Patch match 30%</b>: individual annotated patches matched one-to-one by a mask. Low partly because annotators traced
            rust as many small patches while SAM returns fewer, larger regions.
          </li>
        </ul>
        <p className="muted">Source: benchmark/RESULTS.md in the repository.</p>
      </div>
    </details>
  );
}
