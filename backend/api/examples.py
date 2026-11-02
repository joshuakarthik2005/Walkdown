"""Finished example runs: saved to disk once, loaded instantly as a fresh run (one copy per visitor).

A saved example holds the agent's session (register, plans, scenario, voice notes), its trace, the model
conversation and the final answers. Paths are stored relative to the clip folder, so the files work on any
WALKDOWN_DATA_DIR. Files are gzip-compressed pickles written and read only by this module; never load one
from an untrusted source.

Build or refresh the examples (needs the sample clips' caches; costs about $0.1 of Meta credit):

    python -m backend.api.examples --voice G:/walkdown-data/footage/voice_note_01.m4a
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import os
import pickle
import time
from pathlib import Path

from backend.agent.clip import Clip
from backend.agent.loop import WalkdownAgent
from backend.agent.tools import AgentSession
from backend.clients.cost import CostLedger

EXAMPLES_DIR = Path(os.environ.get("WALKDOWN_DATA_DIR", "G:/walkdown-data")) / "examples"
FORMAT = 1


def _rel(clip: Clip, p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(clip.dir.resolve()).as_posix()
    except ValueError:
        return Path(p).name  # older absolute paths: frames live in <clip>/frames


def save_run(path: Path, agent: WalkdownAgent, answers: list[str], meta: dict) -> None:
    """Write one finished run (session, trace, conversation, answers) to ``path``."""
    s = agent.s
    session = dataclasses.replace(s, ledger=None, clip=None,
                                  frame_paths={i: _rel(s.clip, p) for i, p in s.frame_paths.items()})
    blob = dict(format=FORMAT, clip_id=s.clip.clip_id, session=session, trace=agent.trace, messages=agent.messages,
                answers=answers, effort=agent.effort, meta=meta, saved_at=time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=6) as f:
        pickle.dump(blob, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_run(path: Path, ledger_factory=CostLedger) -> tuple[WalkdownAgent, list[str], dict]:
    """Rebuild an agent (ready for replans and copilot questions) from a saved run."""
    with gzip.open(path, "rb") as f:
        blob = pickle.load(f)  # noqa: S301 - our own files only
    if blob.get("format") != FORMAT:
        raise ValueError(f"{path.name}: unsupported example format")
    clip = Clip(blob["clip_id"])
    s: AgentSession = blob["session"]
    s.clip = clip
    s.ledger = ledger_factory(clip.dir / "cost_ledger.jsonl")
    s.frame_paths = {i: clip.dir / rel if "/" in rel else clip.dir / "frames" / rel for i, rel in s.frame_paths.items()}
    agent = WalkdownAgent(s, reasoning_effort=blob["effort"])
    agent.trace = list(blob["trace"])
    agent.messages = list(blob["messages"])
    return agent, list(blob["answers"]), blob["meta"]


def example_path(example_id: str) -> Path:
    return EXAMPLES_DIR / f"{example_id}.pkl.gz"


def _build(example_id: str, voice: Path | None) -> None:
    from backend.api.samples import EXAMPLES
    from backend.voice.notes import process

    spec = EXAMPLES[example_id]
    clip = Clip(spec["sample"])
    session = AgentSession(clip=clip, ledger=CostLedger(clip.dir / "cost_ledger.jsonl"), live=False,
                           verify_effort="minimal", provider="meta", sam_backend="meta", sensitivity="high_recall")
    agent = WalkdownAgent(session, reasoning_effort="low")
    answers = [agent.run(f"New walkdown clip of {clip.asset.asset_id} ({clip.asset.location}) is uploaded. Inspect it, "
                         "build the register, plan the repairs and explain the plan.")]
    if example_id == "tank-farm":
        if voice is not None:
            session.voice_notes.append(process(voice.read_bytes(), ledger=session.ledger))
        change = dict(type="crew_unavailable", crew_id="C1", start=24, end=96)
        answers.append(agent.run(f"Constraint change at hour 24: {json.dumps(change)}. Replan with epsilon 0.02 and "
                                 "explain what changed."))
    meta = dict(id=example_id, **spec, usd=round(session.ledger.total(), 4), register_entries=len(session.register),
                plan_status=session.plan.stats.status if session.plan else None)
    save_run(example_path(example_id), agent, answers, meta)
    print(json.dumps(meta), flush=True)


def main() -> None:
    from backend.api.samples import EXAMPLES

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids", nargs="*", default=list(EXAMPLES))
    ap.add_argument("--voice", type=Path, help="voice note for the tank-farm example (never committed)")
    args = ap.parse_args()
    for example_id in args.ids:
        _build(example_id, args.voice)


if __name__ == "__main__":
    main()
