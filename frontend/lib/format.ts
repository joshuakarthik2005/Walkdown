// Formatting helpers shared by components.

/** Plan hours count from day 0, 00:00. */
export function hourLabel(h: number): string {
  const day = Math.floor(h / 24);
  const hh = String(h % 24).padStart(2, "0");
  return `D${day} ${hh}:00`;
}

export const usd = (v: number) => (v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);

export const SEVERITY_COLOUR: Record<number, string> = {
  1: "var(--sev1)",
  2: "var(--sev2)",
  3: "var(--sev3)",
  4: "var(--sev4)",
  5: "var(--sev5)",
};

export const REASON_TEXT: Record<string, string> = {
  on_earliest_possible: "earliest possible slot",
  permit_lead_time: "waiting for permit",
  outside_shift: "waiting for the crew's shift",
  waiting_for_shutdown_window: "waiting for shutdown window",
  crew_unavailable: "crew unavailable",
  crew_capacity: "crew busy with higher-risk work",
  permit_concurrency: "permit concurrency limit",
  deferred_by_optimiser: "kept in place for plan stability",
  work_in_progress: "work in progress",
  no_skilled_crew: "no crew with the required skill",
  does_not_fit_in_horizon: "too long for the planning horizon",
  permit_not_ready_in_horizon: "permit not ready within the horizon",
  no_shutdown_window_fits: "no shutdown window fits the job",
  crowded_out: "not enough crew hours of that skill in the horizon",
};
