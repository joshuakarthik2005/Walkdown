"""Detection sensitivity: prompt selection per mode and separate verdict caches."""

from types import SimpleNamespace

from backend.agent import tools
from backend.verify.verifier import PROMPTS, Candidate, _user_content
import numpy as np


def session(provider: str, sensitivity: str):
    return SimpleNamespace(provider=provider, sensitivity=sensitivity, verify_effort="minimal", sam_backend="meta",
                           clip=SimpleNamespace(dir=__import__("pathlib").Path("C:/x")))


def test_balanced_uses_v2_in_cloud_only_and_its_own_cache():
    assert tools._prompt_version(session("meta", "high_recall")) == "v1"
    assert tools._prompt_version(session("meta", "balanced")) == "v2"
    assert tools._prompt_version(session("baseten", "balanced")) == "v1"  # On-prem: Muse Spark Open, v1
    a = tools._verdict_cache(session("meta", "high_recall"), "F00001-0")
    b = tools._verdict_cache(session("meta", "balanced"), "F00001-0")
    assert a != b and b.parent.name == "minimal-v2"


def test_v2_prompt_names_box_candidates_v1_does_not():
    c = Candidate("x", np.zeros((8, 8, 3), np.uint8), np.ones((8, 8), bool), (0, 0, 8, 8), 0.5, source="box")
    assert "box detector" in _user_content(c, "v2")[0]["text"]
    assert "segmenter prompt 'rust'" in _user_content(c, "v1")[0]["text"]
    assert PROMPTS["v2"].startswith(PROMPTS["v1"]) and "Look-alike checklist" in PROMPTS["v2"]
