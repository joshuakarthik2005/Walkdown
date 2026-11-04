const REPO = "https://github.com/joshuakarthik2005/Walkdown";
const LIVE = "https://walkdown-zeta.vercel.app/";
// Set NEXT_PUBLIC_DEMO_VIDEO_URL once the demo video is uploaded.
const VIDEO = process.env.NEXT_PUBLIC_DEMO_VIDEO_URL;

/** What to click first, what is cached and what is live, and where the evidence is. */
export function ForJudges({ demoMode }: { demoMode: boolean }) {
  return (
    <details className="panel judges" open>
      <summary>
        <h2>For judges</h2>
      </summary>
      <ol>
        <li>
          <b>Open finished example</b> on the tank farm: the full run, a voice note and a crew-out replan, instantly.
        </li>
        <li>
          Or pick a sample and <b>Run the agent</b>: you watch it decide, verify and plan (about a minute).
        </li>
        <li>
          Then change a constraint (<b>Replan</b>) or ask the copilot a question.
        </li>
      </ol>
      <p className="muted small">
        <b>Cached vs live:</b> samples reuse cached SAM 3.1 and verifier results, so the same frames give the same register; the agent&apos;s
        own decisions, the planner, replans and copilot answers run live.
        {demoMode ? " Uploads run fresh inference within a daily demo budget." : ""}
      </p>
      <div className="row small">
        <a href={LIVE} target="_blank" rel="noreferrer">Live demo</a>
        <a href={`${REPO}#readme`} target="_blank" rel="noreferrer">README</a>
        <a href={`${REPO}/blob/main/benchmark/RESULTS.md`} target="_blank" rel="noreferrer">Benchmark results</a>
        {VIDEO ? (
          <a href={VIDEO} target="_blank" rel="noreferrer">Demo video</a>
        ) : null}
      </div>
    </details>
  );
}
