"use client";
// Inspector copilot: questions about the register and plan, answered only from read-only tool results.
import { useState } from "react";
import * as api from "@/lib/api";
import { usd } from "@/lib/format";

type Turn = { q: string; reply?: api.CopilotReply; error?: string };

export function Copilot({ runId, busy }: { runId: string; busy: boolean }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [waiting, setWaiting] = useState(false);

  async function submit() {
    const q = question.trim();
    if (!q || waiting) return;
    setQuestion("");
    setWaiting(true);
    setTurns((t) => [...t, { q }]);
    try {
      const reply = await api.ask(runId, q);
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, reply } : x)));
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: String(e) } : x)));
    } finally {
      setWaiting(false);
    }
  }

  return (
    <div className="copilot">
      {turns.map((t, i) => (
        <div key={i} className="copilot-turn">
          <div className="copilot-q">{t.q}</div>
          {t.reply && (
            <>
              <div className="copilot-a">{t.reply.answer}</div>
              <div className="muted mono copilot-src">
                from {t.reply.tool_calls.map((c) => c.name.replaceAll("_", " ")).join(", ") || "no tool"} · {usd(t.reply.usd)}
              </div>
            </>
          )}
          {t.error && <div className="error-box">{t.error}</div>}
          {!t.reply && !t.error && <div className="muted">looking it up…</div>}
        </div>
      ))}
      <div className="row">
        <input
          value={question}
          placeholder="e.g. Why is W02 not scheduled? What does crew C1 do tomorrow?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          disabled={busy || waiting}
        />
        <button onClick={submit} disabled={busy || waiting || !question.trim()}>Ask</button>
      </div>
      <div className="muted copilot-src">Answers come only from the register, the plan and the planner&apos;s reasons.</div>
    </div>
  );
}
