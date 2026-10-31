r"""Spawn a function of a DEPLOYED Modal app and exit, so no local process holds the call.

A killed local ``modal run --detach`` client cancelled a running training call (2026-10-31, Glimmer v2), so long
GPU jobs are started as spawned calls on deployed apps: they run to completion or to the function's hard timeout
whatever happens locally. The call id is appended to WALKDOWN_DATA_DIR/runs/modal_calls.jsonl; results are
written by the function itself to its volume.

    .venv\Scripts\python.exe -m benchmark.modal_spawn walkdown-glimmer train_run '{"budget_min": 130, "run": "v2"}'
    .venv\Scripts\python.exe -m benchmark.modal_spawn --status <call_id>
"""

from __future__ import annotations

import json
import sys
import time

import modal

from benchmark.download_dataset import DATA_DIR

LOG = DATA_DIR / "runs" / "modal_calls.jsonl"


def main() -> int:
    if sys.argv[1] == "--status":
        call = modal.FunctionCall.from_id(sys.argv[2])
        try:
            print(json.dumps(call.get(timeout=0))[:3000])
        except TimeoutError:
            print("running")
        return 0
    app, fn, kwargs = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    call = modal.Function.from_name(app, fn).spawn(**kwargs)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(t=time.time(), app=app, fn=fn, kwargs=kwargs, call_id=call.object_id)) + "\n")
    print(call.object_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
