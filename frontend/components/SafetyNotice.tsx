// Disclosure of known limitations (Muse Spark Open Usage Policy, section 4). Figures are measured on the held-out
// test split; see benchmark/RESULTS.md. Shown in every mode.
export function SafetyNotice() {
  return (
    <div className="safety" role="note">
      <strong>Decision support only.</strong> Walkdown never operates or controls plant equipment; every repair, isolation
      and shutdown needs approval by a qualified person. It <strong>misses corrosion</strong> (on our test set it covered
      37–87% of annotated corrosion area, depending on the pipeline) and <strong>flags things that are not corrosion</strong>.
      Severity grades are consistency-checked, not accuracy-validated. Not a substitute for certified inspection programmes
      (API 570 / 510 / 653, RBI).
    </div>
  );
}

export function Attribution() {
  return <span className="attribution">Built with Muse Spark Open</span>;
}
