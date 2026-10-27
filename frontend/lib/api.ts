// Thin client for the Walkdown FastAPI backend.
import type { FrameInfo, PlanResponse, Register, RunStatus, TraceEvent } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadClip(files: File[], asset: { asset_id: string; asset_type: string; pressurised: boolean; location: string }) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  form.append("asset_id", asset.asset_id);
  form.append("asset_type", asset.asset_type);
  form.append("pressurised", String(asset.pressurised));
  form.append("location", asset.location);
  return json<{ clip_id: string; duration_s: number }>(await fetch(`${API_URL}/clips`, { method: "POST", body: form }));
}

export async function startRun(clip_id: string, live: boolean) {
  return json<{ run_id: string }>(
    await fetch(`${API_URL}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_id, live }),
    }),
  );
}

export const getStatus = async (id: string) => json<RunStatus>(await fetch(`${API_URL}/runs/${id}`));
export const getTrace = async (id: string, since: number) =>
  json<{ status: string; next: number; events: TraceEvent[] }>(await fetch(`${API_URL}/runs/${id}/trace?since=${since}`));
export const getRegister = async (id: string) => json<Register>(await fetch(`${API_URL}/runs/${id}/register`));
export const getPlan = async (id: string) => json<PlanResponse>(await fetch(`${API_URL}/runs/${id}/plan`));
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
