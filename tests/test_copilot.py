"""Inspector copilot: read-only tools over a session, and the loop wiring with a fake model."""

import json
from types import SimpleNamespace

from backend.agent import copilot as cp
from backend.agent import loop as loop_mod
from backend.agent.register import AssetInfo, Detection, RegisterEntry
from backend.planner.models import Assignment
from backend.verify.schema import Grade


def grade(sev: int) -> Grade:
    return Grade.model_validate({"is_defect": True, "defect_type": "corrosion", "severity": sev, "confidence": 0.8,
                                 "recommended_action": "repair", "evidence": {"visual_cues": ["scale"],
                                 "location": "flange", "extent": "small", "mask_fit": "good"}})


def session():
    asset = AssetInfo(asset_id="P-101", asset_type="pipe", pressurised=True, location="", service="lpg")
    reg = [RegisterEntry("W01", asset, [Detection("c1", 0, (0, 0, 5, 5), grade(4), [],
                                                  {"reason": "severity 4", "changed_decision": False,
                                                   "first_severity": 5})], False),
           RegisterEntry("W02", asset, [Detection("c2", 1, (0, 0, 5, 5), grade(2), ["poor_mask_fit"])], True)]
    plan = SimpleNamespace(assignments=[Assignment(defect_id="W01", crew_id="C1", start=8, end=12),
                                        Assignment(defect_id="B03", crew_id="C2", start=30, end=40)],
                           unscheduled=["W02"], critical_unscheduled=[], moved_jobs=[],
                           stats=SimpleNamespace(status="OPTIMAL", gap=0.0), explanations=[])
    return SimpleNamespace(register=reg, plan=plan, scenario=SimpleNamespace(), plan_history=[], provider="meta",
                           ledger=SimpleNamespace(total=lambda: 0.0, add=lambda e: e))


def test_register_filters_and_senior_review():
    s = session()
    assert [e["defect_id"] for e in cp.get_register(s, min_severity=3)["entries"]] == ["W01"]
    assert [e["defect_id"] for e in cp.get_register(s, needs_review_only=True)["entries"]] == ["W02"]
    w01 = cp.get_register(s, defect_ids=["W01"])["entries"][0]
    assert w01["senior_review"]["first_severity"] == 5 and w01["service"] == "lpg"


def test_schedule_filters():
    s = session()
    out = cp.get_schedule(s, crew_id="C1")
    assert out["status"] == "OPTIMAL" and [a["defect_id"] for a in out["assignments"]] == ["W01"]
    assert out["assignments"][0]["from_walkdown"] and out["unscheduled"] == ["W02"]
    assert [a["defect_id"] for a in cp.get_schedule(s, from_hour=20)["assignments"]] == ["B03"]


def test_grouped_defect_is_found_through_its_work_package():
    """In the grouped plan a defect is scheduled as its package: asking about the defect returns the package."""
    s = session()
    s.register[1].package_id = "WP1"
    s.plan.assignments.append(Assignment(defect_id="WP1", crew_id="C1", start=50, end=60))
    out = cp.get_schedule(s, defect_ids=["W02"])
    assert [a["defect_id"] for a in out["assignments"]] == ["WP1"] and out["assignments"][0]["from_walkdown"]
    assert out["repaired_in_work_package"] == {"W02": "WP1"}
    assert cp.get_register(s, defect_ids=["W02"])["entries"][0]["work_package"] == "WP1"
    assert cp.explain_plan(s, ["W02"])["repaired_in_work_package"] == {"W02": "WP1"}


def test_copilot_uses_only_read_only_tools(monkeypatch):
    calls = iter([
        SimpleNamespace(tool_calls=[SimpleNamespace(id="t1", function=SimpleNamespace(
            name="get_schedule", arguments=json.dumps({"defect_ids": ["W01"]})))], content=""),
        SimpleNamespace(tool_calls=None, content="W01 is with crew C1 from hour 8 to 12."),
    ])
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None,
                            completion_tokens_details=None)
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=next(calls))], usage=usage))))
    monkeypatch.setattr(loop_mod, "meta_client", lambda: fake)
    agent = cp.copilot(session())
    assert set(agent.tools) == {"get_register", "get_schedule", "explain_plan", "get_resources"}
    assert "replan" not in agent.tools and "segment_frames" not in agent.tools
    answer = agent.run("When is W01 fixed?")
    assert "C1" in answer
    tool = [e for e in agent.trace if e.kind == "tool"][0]
    assert tool.name == "get_schedule" and tool.error is None and tool.result["assignments"][0]["crew"] == "C1"
