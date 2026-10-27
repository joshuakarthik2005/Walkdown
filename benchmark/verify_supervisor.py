"""Unattended supervisor for the full verifier run: restart from cache until done or out of budget.

Runs ``benchmark.verify_scale`` in 30-minute chunks (4 processes x 2 call
threads = 8 concurrent calls). The $ cap applies to *new* spend across all
chunks and restarts: the ledger total for the verifier at the first start is
saved and every chunk gets only the remaining budget. A crashed chunk is
restarted after a short backoff. Progress goes to
WALKDOWN_DATA_DIR/runs/verify_supervisor.log and verify_supervisor_status.json.

    .venv\\Scripts\\python.exe -m benchmark.verify_supervisor --max-usd 34
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from benchmark.download_dataset import DATA_DIR
from benchmark.splits import load_split
from benchmark.verify_scale import journal_path, read_journal

RUNS = DATA_DIR / "runs"
LEDGER = RUNS / "cost_ledger.jsonl"
STATE = RUNS / "verify_supervisor_state.json"
STATUS = RUNS / "verify_supervisor_status.json"
LOG = RUNS / "verify_supervisor.log"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def verifier_spend() -> float:
    """Total ledger spend on hosted verifier calls (job 'verify-meta')."""
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["job"] == "verify-meta":
            total += e["usd"]
    return total


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--chunk-minutes", type=float, default=30)
    args = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if "baseline_usd" not in state:
        state = dict(baseline_usd=verifier_spend(), started=time.time())
        STATE.write_text(json.dumps(state))
    images = load_split(args.split)
    failures = 0
    while True:
        done = read_journal(journal_path(args.split, "low"))
        n_done = sum(r in done for r in images)
        spent = verifier_spend() - state["baseline_usd"]
        elapsed_h = (time.time() - state["started"]) / 3600
        STATUS.write_text(json.dumps(dict(images_done=n_done, images=len(images),
                                          candidates_done=sum(len(done[r]) for r in images if r in done),
                                          new_spend_usd=round(spent, 3), elapsed_h=round(elapsed_h, 2),
                                          updated=time.strftime("%Y-%m-%d %H:%M:%S"))))
        if n_done >= len(images):
            log(f"complete: {n_done}/{len(images)} images, new spend ${spent:.2f}")
            return 0
        if spent >= args.max_usd:
            log(f"budget reached: new spend ${spent:.2f} >= ${args.max_usd:.2f}; stopping at {n_done}/{len(images)}")
            return 1
        log(f"chunk start: {n_done}/{len(images)} images done, new spend ${spent:.2f}")
        rc = subprocess.run(
            [sys.executable, "-m", "benchmark.verify_scale", args.split, "--workers", "4",
             "--max-usd", f"{args.max_usd - spent:.4f}", "--max-minutes", str(args.chunk_minutes)],
            cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=(RUNS / "verify_scale_stderr.log").open("a"),
        ).returncode
        if rc != 0:
            failures += 1
            log(f"chunk exited with code {rc} (failure {failures}); restarting from cache after backoff")
            if failures >= 10:
                log("too many consecutive failures; stopping")
                return 2
            time.sleep(min(300, 30 * failures))
        else:
            failures = 0


if __name__ == "__main__":
    sys.exit(main())
