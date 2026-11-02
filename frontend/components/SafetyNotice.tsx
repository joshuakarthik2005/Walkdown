// Disclosure of known limitations (Muse Spark Open Usage Policy, section 4). Figures are measured on the held-out
// test split; see benchmark/RESULTS.md. Shown in every mode: one always-visible line, full text one click away.
export function SafetyNotice() {
  return (
    <details className="safety" role="note">
      <summary>
        <strong>Decision support only</strong> · human approval required · <Attribution /> · <span className="link">Limitations</span>
      </summary>
      <div className="safety-body">
        <strong>Decision support only.</strong> Walkdown never operates or controls plant equipment; every repair, isolation
        and shutdown needs approval by a qualified person. It <strong>misses corrosion</strong> (on our test set the default pipeline found
        corrosion on 98% of images that have it but covered 84% of the annotated area and matched only 30% of individual
        patches) and <strong>flags things that are not corrosion</strong>.
        Severity grades are consistency-checked, not accuracy-validated. Not a substitute for certified inspection programmes
        (API 570 / 510 / 653, RBI).
      </div>
    </details>
  );
}

export function Attribution() {
  return <span className="attribution">Built with Muse Spark Open</span>;
}
