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
  frames: number[];
  needs_review: boolean;
  grade: Grade;
  detections: { candidate_id: string; frame: number; box: number[]; flags: string[] }[];
}

export interface Register {
  asset: { asset_id: string; asset_type: string; pressurised: boolean; location: string; service: string | null };
  entries: RegisterEntry[];
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
  defects: { id: string; asset: string; severity: number; skill: string; repair_hours: number; needs_shutdown: boolean }[];
  crews: { id: string; name: string; skills: string[]; shift_start: number; shift_hours: number; unavailable: { start: number; end: number }[] }[];
  windows: { id: string; start: number; end: number }[];
}

export interface PlanResponse {
  plan: Plan;
  scenario: Scenario;
  history: { kind: string; now: number; exposure: number; moved?: number; epsilon?: number | null }[];
  walkdown_defect_ids: string[];
}

export interface FrameInfo {
  frame: number;
  detections: { defect_id: string; candidate_id: string; box: number[]; severity: number }[];
}
