// Thin client for the Walkdown FastAPI backend.
import type { FrameInfo, PlanResponse, PlanView, Register, RunStatus, TraceEvent } from "./types";

// Default: the API on port 8000 of the host serving this page (avoids localhost vs 127.0.0.1 mismatches).
// A trailing slash in NEXT_PUBLIC_API_URL is dropped (it would turn every path into "//path").
export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8000` : "http://127.0.0.1:8000")
).replace(/\/+$/, "");

/** An error whose message is safe to show to a user (never raw server text). */
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export const UNREACHABLE = "Can't reach the Walkdown server. It may be starting up; retrying.";

async function call(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch {
    throw new ApiError(UNREACHABLE, 0);
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json())?.detail;
    } catch {
      /* not JSON */
    }
    // The API writes user-facing messages for 4xx (budget, limits, bad input) and for 502 (a model call failed);
    // anything else gets a generic line.
    const msg =
      (res.status < 500 || res.status === 502) && typeof detail === "string"
        ? detail
        : res.status === 413
          ? "File too large."
          : "Something went wrong on the server. Try again, or open a finished example.";
    throw new ApiError(msg, res.status);
  }
  return res.json() as Promise<T>;
}

/** A message for any thrown value, suitable for the UI. */
export const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

export interface ServerConfig {
  demo_mode: boolean;
  daily_cap_usd: number | null;
  budget_available: boolean;
  max_upload_mb: number;
  max_duration_s: number | null;
  onprem_runs: boolean;
}

export interface Sample {
  id: string;
  title: string;
  description: string;
  credit: { author: string; source: string; licence: string; url: string };
  example: string;
  asset: { asset_id: string; asset_type: string; pressurised: boolean; location: string; service: string | null };
  duration_s: number;
  thumbnail: string;
}

export interface Example {
  id: string;
  sample: string;
  title: string;
  includes: string[];
}

export const getConfig = async () => json<ServerConfig>(await call(`${API_URL}/config`));
export const getSamples = async () => json<{ samples: Sample[] }>(await call(`${API_URL}/samples`));
export const getExamples = async () => json<{ examples: Example[] }>(await call(`${API_URL}/examples`));
export const openExample = async (id: string) =>
  json<{ run_id: string; example: string; sample: string; title: string }>(await call(`${API_URL}/examples/${id}`));

export async function uploadClip(files: File[], asset: { asset_id: string; asset_type: string; pressurised: boolean; location: string; service: string }) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  form.append("asset_id", asset.asset_id);
  form.append("asset_type", asset.asset_type);
  form.append("pressurised", String(asset.pressurised));
  form.append("location", asset.location);
  form.append("service", asset.service);
  return json<{ clip_id: string; duration_s: number }>(await call(`${API_URL}/clips`, { method: "POST", body: form }));
}

export type Mode = "cloud" | "onprem";

export type Sensitivity = "high_recall" | "balanced";

export async function startRun(clip_id: string, live: boolean, mode: Mode = "cloud", sensitivity: Sensitivity = "high_recall") {
  return json<{ run_id: string }>(
    await call(`${API_URL}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_id, live, provider: mode === "onprem" ? "baseten" : "meta", sensitivity }),
    }),
  );
}

export const getStatus = async (id: string) => json<RunStatus>(await call(`${API_URL}/runs/${id}`));
export const getTrace = async (id: string, since: number) =>
  json<{ status: string; next: number; events: TraceEvent[] }>(await call(`${API_URL}/runs/${id}/trace?since=${since}`));
export const getRegister = async (id: string) => json<Register>(await call(`${API_URL}/runs/${id}/register`));
export const getPlan = async (id: string, view?: PlanView) =>
  json<PlanResponse>(await call(`${API_URL}/runs/${id}/plan${view ? `?view=${view}` : ""}`));
export const getFrames = async (id: string) => json<{ frames: FrameInfo[] }>(await call(`${API_URL}/runs/${id}/frames`));
export const frameUrl = (id: string, frame: number) => `${API_URL}/runs/${id}/frames/${frame}.jpg`;

export async function postChange(id: string, change: Record<string, unknown>, now_hour: number, epsilon: number) {
  return json<{ status: string }>(
    await call(`${API_URL}/runs/${id}/changes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ change, now_hour, epsilon }),
    }),
  );
}

export interface CopilotReply {
  answer: string;
  usd: number;
  tool_calls: { name: string; args: Record<string, unknown>; summary: string }[];
}

export async function ask(id: string, question: string) {
  return json<CopilotReply>(
    await call(`${API_URL}/runs/${id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
  );
}

export async function uploadVoice(id: string, file: File) {
  const form = new FormData();
  form.append("audio", file);
  return json<import("./types").VoiceNoteResult>(await call(`${API_URL}/runs/${id}/voice`, { method: "POST", body: form }));
}

export interface Measure {
  value: number;
  k: number;
  n: number;
  ci: [number, number];
}

export interface OperatingPoint {
  label: string;
  mode: "cloud" | "on-prem";
  default: boolean;
  verifier: string;
  recall: Measure;
  false_alarm_images: Measure;
  note: string;
}

export const getSensitivity = async () =>
  json<{ default: Sensitivity; options: Record<Sensitivity | "on_prem", OperatingPoint> }>(await call(`${API_URL}/sensitivity`));
