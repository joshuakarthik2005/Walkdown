// Thin client for the Walkdown FastAPI backend.
import type { FrameInfo, PlanResponse, PlanView, Register, RunStatus, TraceEvent } from "./types";

// Default: the API on port 8000 of the host serving this page (avoids localhost vs 127.0.0.1 mismatches).
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8000` : "http://127.0.0.1:8000");

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadClip(files: File[], asset: { asset_id: string; asset_type: string; pressurised: boolean; location: string; service: string }) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  form.append("asset_id", asset.asset_id);
  form.append("asset_type", asset.asset_type);
  form.append("pressurised", String(asset.pressurised));
  form.append("location", asset.location);
  form.append("service", asset.service);
  return json<{ clip_id: string; duration_s: number }>(await fetch(`${API_URL}/clips`, { method: "POST", body: form }));
}

export type Mode = "cloud" | "onprem";

export type Sensitivity = "high_recall" | "balanced";

export async function startRun(clip_id: string, live: boolean, mode: Mode = "cloud", sensitivity: Sensitivity = "high_recall") {
  return json<{ run_id: string }>(
    await fetch(`${API_URL}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_id, live, provider: mode === "onprem" ? "baseten" : "meta", sensitivity }),
    }),
  );
}

export const getStatus = async (id: string) => json<RunStatus>(await fetch(`${API_URL}/runs/${id}`));
export const getTrace = async (id: string, since: number) =>
  json<{ status: string; next: number; events: TraceEvent[] }>(await fetch(`${API_URL}/runs/${id}/trace?since=${since}`));
export const getRegister = async (id: string) => json<Register>(await fetch(`${API_URL}/runs/${id}/register`));
export const getPlan = async (id: string, view?: PlanView) =>
  json<PlanResponse>(await fetch(`${API_URL}/runs/${id}/plan${view ? `?view=${view}` : ""}`));
export const getFrames = async (id: string) => json<{ frames: FrameInfo[] }>(await fetch(`${API_URL}/runs/${id}/frames`));
export const frameUrl = (id: string, frame: number) => `${API_URL}/runs/${id}/frames/${frame}.jpg`;

export async function postChange(id: string, change: Record<string, unknown>, now_hour: number, epsilon: number) {
  return json<{ status: string }>(
    await fetch(`${API_URL}/runs/${id}/changes`, {
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
    await fetch(`${API_URL}/runs/${id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
  );
}

export async function uploadVoice(id: string, file: File) {
  const form = new FormData();
  form.append("audio", file);
  return json<import("./types").VoiceNoteResult>(await fetch(`${API_URL}/runs/${id}/voice`, { method: "POST", body: form }));
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
  json<{ default: Sensitivity; options: Record<Sensitivity | "on_prem", OperatingPoint> }>(await fetch(`${API_URL}/sensitivity`));
