"""The Walkdown agent: Muse Spark with tool calling drives inspection, planning and replanning.

Chat Completions tool-calling format, per https://dev.meta.ai/docs/tool-calling:
tools under ``function``, ``tool_choice`` left at "auto" (the only supported
value), the full assistant message with ``tool_calls`` appended before one
``tool`` message per call. Every model turn and tool call is logged as a
structured trace event (inputs and outputs summarised, timing, tokens, cost).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from backend.agent.tools import TOOL_SCHEMAS, TOOLS, AgentSession
from backend.clients.cost import CostEntry, muse_cost
from backend.clients.meta import meta_client, with_retries
from backend.verify.verifier import BASETEN_MODEL, baseten_client

MODEL = "muse-spark-1.3"

SYSTEM_PROMPT = """You are Walkdown, an inspection-and-planning agent for an energy plant. A technician has \
recorded a walkdown clip of one asset. Your job: find corrosion, verify it, add it to the defect register, \
schedule repairs, and explain the plan. Work autonomously with your tools:

1. segment_frames: start with a coarse pass over the whole clip (fps 0.5-1). If a stretch shows candidates \
or looks unclear, inspect it again at a higher fps. Do not resample the same range at the same rate.
2. verify_candidate: verify every candidate (up to 20 ids per call). Rejected candidates are false positives. Severe
   (severity 4+) or uncertain grades are re-checked automatically by a senior reviewer (Muse Wonder); its grade is
   final. Mention it when a senior review changed a decision or a severity.
3. build_register once all candidates are verified.
4. plan_maintenance to schedule the register together with the existing backlog.
5. explain_plan for the walkdown defects, then answer.

When the user reports a constraint change, call replan (then explain_plan) instead of starting over.

Rules for your final answer: write for a maintenance planner, in plain language, at most about 150 words: one line on what was found, then 3-6 short bullets (most urgent jobs with crew and day/hour, what could not be scheduled and why, anything needing review). Do not list every defect id; group them. Do not quote internal field names (likelihood, risk_weight, consequence_factor, null); give the gap as a percentage. Mention the line service only when it is known. Every number, crew, \
time and reason must come from tool results. Explain scheduling only with the reason codes returned by \
explain_plan (e.g. permit_lead_time, waiting_for_shutdown_window, crew_capacity); never invent a reason. \
Priority is risk = likelihood (from severity) x consequence of the line's service (explain_plan gives the service and consequence_factor); mention it when it explains an ordering. For crowded_out defects, say plainly that there are not enough crew hours of that skill in the horizon, \
using the numbers in the reason's detail. Always state the solver status (OPTIMAL or FEASIBLE) and the gap; \
never call a FEASIBLE plan optimal. \
Hours are counted from the start of the plan (hour 0 = day 0, 00:00). Mention entries that need review."""


class TraceEvent(BaseModel):
    """One step of the agent run, for the UI's live trail."""

    step: int
    kind: Literal["llm", "tool", "final", "error"]
    name: str
    args: dict = Field(default_factory=dict)
    summary: str = ""
    result: dict | None = None
    started_at: float
    duration_s: float
    usd: float = 0.0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    error: str | None = None


def _summarise(name: str, result: dict) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if name == "segment_frames":
        return f"{result['frames_segmented']} frames, {result['new_candidates']} new candidates"
    if name == "verify_candidate":
        acc = sum(1 for r in result["results"] if r.get("is_defect"))
        senior = result.get("senior_reviews", 0)
        return (f"{result['verified']} verified, {acc} accepted, {result['verified'] - acc} rejected"
                + (f", {senior} senior review{'s' if senior != 1 else ''} (Muse Wonder)" if senior else ""))
    if name == "build_register":
        return f"{result['register_entries']} register entries, {len(result['needs_review'])} need review"
    if name in ("plan_maintenance", "replan"):
        s = f"{result['status']}, {result['scheduled']} scheduled, {len(result['unscheduled'])} unscheduled"
        return s + (f", {len(result['moved_jobs'])} moved" if name == "replan" else "")
    if name == "explain_plan":
        return f"{len(result['explanations'])} explanations"
    return ""


class WalkdownAgent:
    """Runs the tool-calling loop over an AgentSession and keeps the message history for follow-ups."""

    def __init__(self, session: AgentSession, *, reasoning_effort: str = "low", max_steps: int = 25,
                 on_event: Callable[[TraceEvent], None] | None = None) -> None:
        self.s = session
        self.effort = reasoning_effort
        self.max_steps = max_steps
        self.on_event = on_event
        self.trace: list[TraceEvent] = []
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.provider = getattr(session, "provider", "meta")
        self.model = MODEL if self.provider == "meta" else BASETEN_MODEL

    def _complete(self):
        """One model turn. Muse Spark Open on Baseten gets the same messages and tools; reasoning effort and
        prompt-cache keys are Meta Model API parameters and are not sent to it."""
        if self.provider == "meta":
            return meta_client().chat.completions.create(
                model=MODEL, messages=self.messages, tools=TOOL_SCHEMAS, reasoning_effort=self.effort,
                max_tokens=6000, prompt_cache_key="walkdown-agent-v1")
        return baseten_client().chat.completions.create(
            model=BASETEN_MODEL, messages=self.messages, tools=TOOL_SCHEMAS, max_tokens=6000)

    def _emit(self, ev: TraceEvent) -> None:
        self.trace.append(ev)
        if self.on_event:
            self.on_event(ev)

    def run(self, user_message: str) -> str:
        """Send a user message and loop until the model answers in plain text."""
        self.messages.append({"role": "user", "content": user_message})
        for _ in range(self.max_steps):
            t0 = time.time()
            resp = with_retries(lambda: self._complete())
            u = resp.usage
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
            usd = muse_cost(u.prompt_tokens, u.completion_tokens, cached)
            self.s.ledger.add(CostEntry(job="agent-llm", model=self.model, usd=usd, input_tokens=u.prompt_tokens,
                                        cached_tokens=cached, output_tokens=u.completion_tokens,
                                        reasoning_tokens=reasoning))
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            self._emit(TraceEvent(step=len(self.trace), kind="llm", name=self.model, started_at=t0,
                                  duration_s=time.time() - t0, usd=usd, input_tokens=u.prompt_tokens,
                                  cached_tokens=cached, output_tokens=u.completion_tokens, reasoning_tokens=reasoning,
                                  summary=(f"calls {', '.join(c.function.name for c in calls)}" if calls
                                           else "final answer")))
            if not calls:
                answer = msg.content or ""
                self.messages.append({"role": "assistant", "content": answer})
                self._emit(TraceEvent(step=len(self.trace), kind="final", name="answer", summary=answer[:300],
                                      started_at=time.time(), duration_s=0.0))
                return answer
            self.messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name,
                                                              "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                self.messages.append({"role": "tool", "tool_call_id": c.id,
                                      "content": json.dumps(self._call_tool(c.function.name, c.function.arguments))})
        self._emit(TraceEvent(step=len(self.trace), kind="error", name="max_steps", started_at=time.time(),
                              duration_s=0.0, error=f"stopped after {self.max_steps} model turns"))
        return "Stopped: step limit reached before a final answer."

    def _call_tool(self, name: str, arguments: str) -> dict:
        t0 = time.time()
        spent_before = self.s.ledger.total()
        try:
            args = json.loads(arguments or "{}")
            if name not in TOOLS:
                raise ValueError(f"unknown tool {name!r}")
            result = TOOLS[name](self.s, **args)
            error = result.get("error")
        except Exception as err:  # the model gets the error and can recover; the trace records it
            args = args if isinstance(locals().get("args"), dict) else {"raw": arguments}
            result, error = {"error": f"{type(err).__name__}: {err}"[:500]}, f"{type(err).__name__}: {err}"[:500]
        self._emit(TraceEvent(step=len(self.trace), kind="tool", name=name, args=args,
                              summary=_summarise(name, result), result=result, started_at=t0,
                              duration_s=time.time() - t0, usd=self.s.ledger.total() - spent_before, error=error))
        return result
