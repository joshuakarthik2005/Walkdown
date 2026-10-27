import json
from types import SimpleNamespace

import numpy as np

from backend.agent import loop as loop_mod
from backend.agent.register import AssetInfo, Detection, build_register, to_planner_defect
from backend.agent.tools import TOOL_SCHEMAS, TOOLS
from backend.verify.schema import Grade


def _grade(**kw) -> Grade:
    base = {"is_defect": True, "defect_type": "corrosion", "severity": 3, "confidence": 0.8,
            "evidence": {"visual_cues": ["flaking"], "location": "support", "extent": "small", "mask_fit": "good"},
            "recommended_action": "clean_and_recoat"}
    base.update(kw)
    return Grade.model_validate(base)


def test_register_merges_nearby_frames_and_keeps_worst_grade():
    asset = AssetInfo("PIPE-1")
    dets = [Detection("a", 10, (100, 100, 200, 200), _grade(severity=2)),
            Detection("b", 11, (105, 102, 205, 198), _grade(severity=4, confidence=0.9)),
            Detection("c", 11, (400, 400, 450, 450), _grade()),
            Detection("d", 30, (100, 100, 200, 200), _grade())]  # too far in time: separate
    reg = build_register(dets, asset)
    assert [len(e.detections) for e in reg] == [2, 1, 1]
    assert reg[0].grade.severity == 4 and reg[0].frames == [10, 11]
    assert [e.defect_id for e in reg] == ["W01", "W02", "W03"]
    photos = build_register(dets, asset, merge_across_frames=False)
    assert len(photos) == 4


def test_planner_mapping_rules():
    pipe = AssetInfo("PIPE-1", asset_type="pipe", pressurised=True)
    tank = AssetInfo("TANK-1", asset_type="tank", pressurised=False)
    entry = lambda g, a=pipe: build_register([Detection("x", 0, (0, 0, 10, 10), g)], a)[0]  # noqa: E731
    light = to_planner_defect(entry(_grade(severity=2)), found_at=5)
    assert (light.skill, light.permit, light.needs_shutdown, light.repair_hours, light.found_at) == \
        ("coating", None, False, 3, 5)
    heavy = to_planner_defect(entry(_grade(severity=4, recommended_action="repair")), found_at=0)
    assert (heavy.skill, heavy.permit, heavy.needs_shutdown) == ("welding", "hot_work", True)
    tank_heavy = to_planner_defect(entry(_grade(severity=5), tank), found_at=0)
    assert tank_heavy.permit == "confined_space" and not tank_heavy.needs_shutdown
    leak = to_planner_defect(entry(_grade(defect_type="leak_stain")), found_at=0)
    assert (leak.skill, leak.permit, leak.needs_shutdown) == ("mechanical", "cold_work", True)
    assert 0 < heavy.failure_risk <= 0.95


def test_tool_schemas_match_implementations():
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert set(names) == set(TOOLS)
    for t in TOOL_SCHEMAS:
        assert t["type"] == "function" and t["function"]["parameters"]["type"] == "object"


def _fake_response(tool_calls=None, content=None):
    calls = [SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
             for i, (n, a) in enumerate(tool_calls or [])]
    msg = SimpleNamespace(content=content, tool_calls=calls or None)
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=800),
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=50))
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def test_agent_loop_runs_tools_traces_and_recovers_from_tool_errors(monkeypatch):
    from backend.clients.cost import CostLedger
    responses = iter([
        _fake_response([("explain_plan", {}), ("no_such_tool", {})]),
        _fake_response(content="All done."),
    ])
    sent = []

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    sent.append({**kw, "messages": list(kw["messages"])})
                    return next(responses)

    monkeypatch.setattr(loop_mod, "meta_client", lambda: FakeClient)
    session = SimpleNamespace(ledger=CostLedger(), plan=None)
    agent = loop_mod.WalkdownAgent(session)
    assert agent.run("go") == "All done."
    kinds = [(e.kind, e.name) for e in agent.trace]
    assert kinds == [("llm", "muse-spark-1.3"), ("tool", "explain_plan"), ("tool", "no_such_tool"),
                     ("llm", "muse-spark-1.3"), ("final", "answer")]
    assert agent.trace[1].result == {"error": "no plan yet"}
    assert agent.trace[2].error and "unknown tool" in agent.trace[2].error
    # the assistant tool_calls message precedes one tool message per call, in order
    roles = [m["role"] for m in sent[1]["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "tool"]
    assert sent[1]["messages"][3]["tool_call_id"] == "call_0"
    assert agent.trace[0].usd > 0 and agent.trace[0].cached_tokens == 800
    assert sent[0]["tools"] and sent[0]["reasoning_effort"] == "low"


def test_normalise_change_accepts_flat_and_nested_forms():
    from backend.agent.tools import normalise_change
    flat = {"type": "crew_unavailable", "crew_id": "C1", "start": 48, "end": 120}
    assert normalise_change(flat) == flat
    assert normalise_change({"crew_unavailable": {"crew_id": "C1", "start": 48, "end": 120}}) == flat
    assert normalise_change({"type": "crew_unavailable",
                             "crew_unavailable": {"crew_id": "C1", "start": 48, "end": 120}}) == flat
    d = {"id": "N1", "asset": "A", "severity": 5, "failure_risk": 0.9, "repair_hours": 6, "skill": "coating"}
    assert normalise_change({"new_defect": d}) == {"type": "new_defect", "defect": d}
    assert normalise_change({"type": "new_defect", "defect": d}) == {"type": "new_defect", "defect": d}
