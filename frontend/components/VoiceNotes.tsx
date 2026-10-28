"use client";
// Inspector voice notes: Muse Voice Transcribe, then structured fields (asset tag, service, remarks, follow-ups).
import { useState } from "react";
import * as api from "@/lib/api";
import type { VoiceNoteResult } from "@/lib/types";

export function VoiceNotes({ runId, notes, onAdded }: { runId: string; notes: VoiceNoteResult[]; onAdded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await api.uploadVoice(runId, file);
      onAdded();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="voice">
      {notes.map((n, i) => (
        <div key={i} className="voice-note">
          <div>
            <strong>Inspector note</strong> · {(n.audio_ms / 1000).toFixed(0)} s
            {n.note?.asset_tag && <> · tag {n.note.asset_tag}</>}
            {n.note?.line_service && <> · {n.note.line_service.replaceAll("_", " ")} service</>}
          </div>
          {n.note && <div>{n.note.summary}</div>}
          {n.note?.remarks.map((r, j) => (
            <div key={j} className="muted">
              {r.location}: {r.description}
              {r.severity_words ? ` (${r.severity_words})` : ""}
            </div>
          ))}
          {!!n.note?.follow_ups.length && <div className="muted">Follow-ups: {n.note.follow_ups.join("; ")}</div>}
          <details className="muted">
            <summary>transcript</summary>
            {n.transcript}
          </details>
        </div>
      ))}
      <label className="row">
        <span>{busy ? "Transcribing…" : "Attach a voice note (WAV)"}</span>
        <input type="file" accept=".wav,audio/wav" disabled={busy} onChange={(e) => upload(e.target.files?.[0])} />
      </label>
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
