"""Minimal Fireworks REST client: datasets, supervised fine-tuning jobs and deployments.

Reads FIREWORKS_API_KEY from .env (never printed). Deployments bill per GPU hour, so every
deployment created through ``deployment`` is deleted in a ``finally`` block, has a wall-clock
cap, and ``assert_no_deployments`` is checked after each job (docs/DECISIONS.md).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from backend.clients.meta import PROJECT_ROOT

API = "https://api.fireworks.ai/v1"
ACCOUNT = "accounts/joshuakarthik2005-tg"
GLIMMER = "accounts/fireworks/models/muse-glimmer-30b"


def _key() -> str:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    key = os.environ.get("FIREWORKS_API_KEY")
    if not key:
        raise RuntimeError("FIREWORKS_API_KEY missing from .env")
    return key


def request(method: str, path: str, body: dict | None = None, *, data: bytes | None = None,
            content_type: str = "application/json") -> dict:
    """One REST call; ``path`` is relative to /v1 (e.g. ``accounts/x/datasets``)."""
    payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"{API}/{path}", data=payload, method=method,
                                 headers={"Authorization": f"Bearer {_key()}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = r.read().decode()
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"Fireworks {method} /{path}: HTTP {err.code} {err.read().decode()[:500]}") from None


def upload_dataset(dataset_id: str, jsonl: Path) -> str:
    """Create a user-uploaded dataset and upload a JSONL file to it; returns the dataset resource name."""
    n = sum(1 for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip())
    request("POST", f"{ACCOUNT}/datasets", {"datasetId": dataset_id, "dataset": {"userUploaded": {}, "exampleCount": str(n)}})
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{jsonl.name}\"\r\n"
            f"Content-Type: application/jsonl\r\n\r\n").encode() + jsonl.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request("POST", f"{ACCOUNT}/datasets/{dataset_id}:upload", data=body,
            content_type=f"multipart/form-data; boundary={boundary}")
    return f"{ACCOUNT}/datasets/{dataset_id}"


def create_sft_job(job_id: str, dataset: str, output_model_id: str, *, base_model: str = GLIMMER, epochs: int = 1,
                   lora_rank: int = 16, learning_rate: float = 1e-4, **extra) -> dict:
    """Start a LoRA SFT job (``loraRank`` is always set: an omitted rank means full-parameter training)."""
    body = {"baseModel": base_model, "dataset": dataset, "outputModel": f"{ACCOUNT}/models/{output_model_id}",
            "epochs": epochs, "loraRank": lora_rank, "learningRate": learning_rate, **extra}
    return request("POST", f"{ACCOUNT}/supervisedFineTuningJobs?supervisedFineTuningJobId={job_id}", body)


def get_sft_job(job_id: str) -> dict:
    return request("GET", f"{ACCOUNT}/supervisedFineTuningJobs/{job_id}")


def list_deployments() -> list[dict]:
    return request("GET", f"{ACCOUNT}/deployments").get("deployments", [])


def assert_no_deployments() -> None:
    """Raise if any deployment is left running (they bill per GPU hour)."""
    live = [d.get("name") for d in list_deployments() if d.get("state") not in ("DELETED", "DELETING")]
    if live:
        raise RuntimeError(f"deployments still present: {live}")


@contextmanager
def deployment(model: str, *, max_hours: float = 2.0, deployment_id: str | None = None):
    """Create an on-demand deployment (min replicas 0), yield its name, always delete it afterwards.

    The caller must stop work once ``deadline`` (seconds since the epoch, yielded) is passed.
    """
    dep_id = deployment_id or f"walkdown-{uuid.uuid4().hex[:8]}"
    dep = request("POST", f"{ACCOUNT}/deployments?deploymentId={dep_id}", {
        "baseModel": model, "minReplicaCount": 0, "maxReplicaCount": 1, "autoscalingPolicy": {"scaleToZeroWindow": "300s"}})
    name = dep.get("name", f"{ACCOUNT}/deployments/{dep_id}")
    try:
        yield name, time.time() + 3600 * max_hours
    finally:
        request("DELETE", name.split("/v1/")[-1] if name.startswith("http") else name)
