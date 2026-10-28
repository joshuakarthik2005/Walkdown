// Shapes returned by the Walkdown FastAPI backend (backend/api/app.py).

export type TraceKind = "llm" | "tool" | "final" | "error";

export interface TraceEvent {
  step: number;
  kind: TraceKind;
  name: string;
  args: Record<string, unknown>;
  summary: string;
  result: Record<string, unknown> | null;
  started_at: number;
  duration_s: number;
  usd: number;
  input_tokens: number;
  cached_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  error: string | null;
}

export interface RunStatus {
  run_id: string;
  status: "running" | "done" | "error";
  error: string | null;
  answers: string[];
  steps: number;
  usd: number;
  elapsed_s: number;
  now_hour: number;
}

export interface Grade {
  is_defect: boolean;
  defect_type: string;
  severity: number;
  confidence: number;
  evidence: { visual_cues: string[]; location: string; extent: string; mask_fit: string };
  recommended_action: string;
}

export interface RegisterEntry {
  defect_id: string;
  package_id: string | null; // planner job (work package) this defect is repaired in
  frames: number[];
  needs_review: boolean;
  grade: Grade;
  detections: { candidate_id: string; frame: number; box: number[]; flags: string[]; senior: SeniorReview | null }[];
}

export interface Register {
  asset: { asset_id: string; asset_type: string; pressurised: boolean; location: string; service: string | null };
  entries: RegisterEntry[];
  voice_notes: VoiceNoteResult[];
}

export interface VoiceNoteResult {
  transcript: string;
  audio_ms: number;
  note: {
    asset_tag: string | null;
    line_service: string | null;
    remarks: { location: string; description: string; severity_words: string }[];
    follow_ups: string[];
    summary: string;
  } | null;
}

export interface Assignment {
  defect_id: string;
  crew_id: string;
  start: number;
  end: number;
}

export interface Reason {
  code: string;
  delay_hours: number | null;
  until_hour: number | null;
  related_ids: string[];
  detail: Record<string, unknown>;
}

export interface Explanation {
  defect_id: string;
  status: "scheduled" | "unscheduled" | "in_progress" | "completed";
  crew_id: string | null;
  start: number | null;
  end: number | null;
  release_hour: number;
  earliest_feasible_start: number | null;
  reasons: Reason[];
  priority: { service: string | null; severity: number; likelihood: number; consequence_factor: number; risk_weight: number; critical: boolean; high: boolean };
}

export interface Plan {
  scenario_name: string;
  now: number;
  assignments: Assignment[];
  unscheduled: string[];
  critical_unscheduled: string[];
  high_unscheduled: string[];
  moved_jobs: string[];
  explanations: Explanation[];
  stats: {
    solver: string;
    status: string;
    objective: number | null;
    best_bound: number | null;
    gap: number | null;
    wall_time_s: number;
    fallback: string | null;
    stages: { stage: string; status: string }[];
  };
  breakdown: { exposure: number; critical_penalty: number; high_penalty: number; move_penalty: number };
}

export interface Scenario {
  name: string;
  horizon_days: number;
  defects: { id: string; asset: string; severity: number; skill: string; extra_skills: string[]; members: string[]; repair_hours: number; needs_shutdown: boolean }[];
  crews: { id: string; name: string; skills: string[]; shift_start: number; shift_hours: number; unavailable: { start: number; end: number }[] }[];
  windows: { id: string; start: number; end: number }[];
}

export interface PlanResponse {
  plan: Plan;
  scenario: Scenario;
  history: { kind: string; now: number; exposure: number; moved?: number; epsilon?: number | null }[];
  walkdown_defect_ids: string[];
  view: PlanView; // the plan shown
  chosen_view: PlanView; // the plan the agent uses (adaptive rule)
  views: PlanView[];
  comparison: PlanComparison | null;
}

export type PlanView = "grouped" | "individual";

export interface PlanMetrics {
  status: string;
  gap: number | null;
  solve_s: number;
  jobs: number;
  exposure: number;
  makespan_h: number;
  defects_unscheduled: number;
  setup_hours_saved: number;
}

export interface PlanComparison {
  chosen: PlanView;
  reason: string;
  individual: PlanMetrics;
  grouped?: PlanMetrics;
}

export interface FrameInfo {
  frame: number;
  detections: { defect_id: string; candidate_id: string; box: number[]; severity: number }[];
}

export interface SeniorReview {
  model: string;
  first_is_defect: boolean;
  first_severity: number;
  first_confidence: number;
  changed_decision: boolean;
  changed_severity: boolean;
  reason: string;
  usd: number;
  latency_s: number;
  valid: boolean;
}
