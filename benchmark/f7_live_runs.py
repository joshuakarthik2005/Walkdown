"""F7: live end-to-end agent runs (Cloud mode, every model call live: no perception or verdict cache).

Rotates over the available clips (dev photo clip + stock demonstration clips) and, every third run, adds a
constraint change after the plan (a crew unavailable for the first shift) to exercise replanning. Per run records:
task success, tool calls, tool-call errors, recoveries (a failing tool later called again successfully), agent
turns, wall time, cost, register size, plan status. Results are appended to a journal so the run is resumable.

Success = the run ends with a final answer, a register was built, a plan exists, explain_plan was called, and (for
replan runs) a replan succeeded.

    .venv\\Scripts\\python.exe -m benchmark.f7_live_runs --runs 50 --max-usd 15
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from backend.agent.clip import Clip
from backend.agent.loop import WalkdownAgent
from backend.agent.tools import AgentSession
from backend.clients.cost import CostLedger
from benchmark.download_dataset import DATA_DIR

CLIPS = ["devdemo", "stock-valve-tank", "stock-vessel", "stock-rusty-pipe", "stock-tank-farm", "stock-clean-piping"]
JOURNAL = DATA_DIR / "runs" / "f7_live_runs.jsonl"
RESULT = Path(__file__).parent / "results" / "f7_live_runs.json"


def one_run(k: int) -> dict:
    clip_id = CLIPS[k % len(CLIPS)]
    clip = Clip(clip_id)
    s = AgentSession(clip=clip, ledger=CostLedger(clip.dir / "cost_ledger.jsonl"), live=True, verify_effort="minimal")
    agent = WalkdownAgent(s)
    t0 = time.time()
    agent.run(f"New walkdown clip of {clip.asset.asset_id} is uploaded. Inspect it, build the register, plan the "
              f"repairs and explain the plan.")
    replan = k % 3 == 2 and s.plan is not None
    if replan:
        crew = s.scenario.crews[0].id
        agent.run(f"Constraint change at hour 0: crew {crew} is unavailable from hour 0 to hour 8. Replan with "
                  f"epsilon 0.02 and explain what moved.")
    tools = [e for e in agent.trace if e.kind == "tool"]
    errors = [e for e in tools if e.error]
    recovered = sum(1 for e in errors if any(t.name == e.name and not t.error and t.step > e.step for t in tools))
    called = {e.name for e in tools if not e.error}
    success = (any(e.kind == "final" for e in agent.trace) and "build_register" in called and s.plan is not None
               and "explain_plan" in called and (not replan or "replan" in called))
    return dict(run=k, clip=clip_id, replan=replan, success=success, tool_calls=len(tools), tool_errors=len(errors),
                error_names=sorted({e.name for e in errors}), first_error=errors[0].error[:200] if errors else None,
                recovered=recovered, agent_turns=sum(1 for e in agent.trace if e.kind == "llm"),
                max_steps_hit=any(e.kind == "error" for e in agent.trace), wall_s=round(time.time() - t0, 1),
                usd=round(s.ledger.total(), 4), register=len(s.register),
                plan=s.plan.stats.status if s.plan else None)


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    return dict(runs=n, success_rate=sum(r["success"] for r in rows) / n if n else None,
                runs_with_tool_errors=sum(r["tool_errors"] > 0 for r in rows),
                tool_errors=sum(r["tool_errors"] for r in rows), recovered=sum(r["recovered"] for r in rows),
                tool_calls=sum(r["tool_calls"] for r in rows), max_steps_hit=sum(r["max_steps_hit"] for r in rows),
                replan_runs=sum(r["replan"] for r in rows),
                wall_s_median=statistics.median(r["wall_s"] for r in rows) if rows else None,
                wall_s_p90=sorted(r["wall_s"] for r in rows)[int(0.9 * (n - 1))] if rows else None,
                usd_median=statistics.median(r["usd"] for r in rows) if rows else None,
                usd_total=round(sum(r["usd"] for r in rows), 2),
                failures=[dict(run=r["run"], clip=r["clip"], first_error=r["first_error"]) for r in rows if not r["success"]])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--max-usd", type=float, required=True)
    args = ap.parse_args()
    rows = [json.loads(l) for l in JOURNAL.read_text(encoding="utf-8").splitlines()] if JOURNAL.exists() else []
    spent = sum(r["usd"] for r in rows)
    for k in range(len(rows), args.runs):
        if spent > args.max_usd:
            print(f"budget reached: ${spent:.2f}", flush=True)
            break
        try:
            r = one_run(k)
        except Exception as err:  # noqa: BLE001  a crash is a failed run, recorded
            r = dict(run=k, clip=CLIPS[k % len(CLIPS)], replan=False, success=False, tool_calls=0, tool_errors=1,
                     error_names=["crash"], first_error=f"{type(err).__name__}: {str(err)[:180]}", recovered=0,
                     agent_turns=0, max_steps_hit=False, wall_s=0.0, usd=0.0, register=0, plan=None)
        spent += r["usd"]
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")
        rows.append(r)
        print(json.dumps(r), flush=True)
    res = summarise(rows)
    RESULT.parent.mkdir(exist_ok=True)
    RESULT.write_text(json.dumps(dict(summary=res, runs=rows), indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
