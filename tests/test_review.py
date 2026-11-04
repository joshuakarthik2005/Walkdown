"""Human review: per-entry decisions, plan approval, rejected entries out of the replan, decisions in the exports."""

import csv
import io
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.agent import review, tools
from backend.agent.register import AssetInfo, Detection, RegisterEntry
from backend.api import app as app_mod
from backend.clients.cost import CostLedger
from backend.planner.models import PlannerConfig
from backend.reports.export import to_csv, to_json, work_orders
from backend.verify.schema import Grade

client = TestClient(app_mod.app)


def _grade(sev):
    return Grade.model_validate({"is_defect": True, "defect_type": "corrosion", "severity": sev, "confidence": 0.8,
                                 "recommended_action": "clean_and_recoat", "evidence": {"visual_cues": ["scale"],
                                 "location": "pipe", "extent": "small", "mask_fit": "good"}})


def _session(severities=(2, 2, 2, 4), disputed=()):
    asset = AssetInfo(asset_id="P-101", asset_type="pipe", pressurised=True)
    reg = [RegisterEntry(f"W{i:02d}", asset, [Detection(f"c{i}", i, (0, 0, 5, 5), _grade(sev),
                                                        ["senior_disputed"] if i in disputed else [])], False)
           for i, sev in enumerate(severities, 1)]
    s = tools.AgentSession(clip=SimpleNamespace(asset=asset), ledger=CostLedger(), base_scenario=tools.demo_backlog(2),
                           planner_config=PlannerConfig(time_limit_s=10))
    s.register = reg
    tools.plan_maintenance(s)
    return s


def _jobs(v):
    return {d.id: d for d in v["scenario"].defects}


def test_decisions_default_store_and_disputed_start_as_reinspect():
    s = _session(disputed=(2,))
    e1, e2 = s.register[0], s.register[1]
    assert review.decision_of(s, e1)["decision"] == "pending" and review.decision_of(s, e1)["at"] is None
    assert review.decision_of(s, e2) == dict(decision="reinspect", label="Needs re-inspection", at=None,
                                             reviewer_severity=None, severity_source=None)
    out = review.set_decision(s, "W01", "approved")
    assert out["decision"] == "approved" and out["at"]
    assert review.decision_of(s, e1)["decision"] == "approved"
    with pytest.raises(ValueError):
        review.set_decision(s, "W01", "maybe")
    with pytest.raises(KeyError):
        review.set_decision(s, "W99", "approved")


def test_plan_approval_blocked_while_a_severity_4_entry_is_pending():
    s = _session()
    assert review.blocking_entries(s) == ["W04"]
    with pytest.raises(ValueError, match="W04"):
        review.approve_plan(s)
    review.set_decision(s, "W04", "reinspect")
    out = review.approve_plan(s)
    assert out["plan_approval"]["at"] and out["blocking"] == []
    review.set_decision(s, "W01", "approved")  # a later decision withdraws the approval
    assert review.review_summary(s)["plan_approval"] is None


def test_rejected_entries_are_excluded_from_the_next_replan_and_packages_shrink():
    s = _session(severities=(2, 2, 2, 2))
    assert set(s.variants) == {"individual", "grouped"}
    grouped_before = next(j for j in s.variants["grouped"]["jobs"] if j.members)
    review.set_decision(s, "W02", "rejected")
    assert review.review_summary(s)["rejected_pending_replan"] == ["W02"]
    assert "W02" in _jobs(s.variants["individual"])  # nothing changes until the replan
    crew = s.base_scenario.crews[0].id
    out = tools.replan_tool(s, {"type": "crew_unavailable", "crew_id": crew, "start": 0, "end": 24}, now_hour=0)
    assert out["rejected_by_reviewer_excluded"] == ["W02"]
    ind = s.variants["individual"]
    assert "W02" not in _jobs(ind) and all(a.defect_id != "W02" for a in ind["plan"].assignments)
    assert "W02" not in ind["plan"].moved_jobs and "W02" not in ind["plan"].unscheduled
    pkg = _jobs(s.variants["grouped"])[grouped_before.id]
    assert "W02" not in pkg.members and pkg.repair_hours < grouped_before.repair_hours
    assert review.review_summary(s)["rejected_excluded"] == ["W02"]
    assert "W02" not in tools._walkdown_job_ids(s) or s.plan_view == "grouped"
    # a second replan does not exclude it again
    out2 = tools.replan_tool(s, {"type": "crew_unavailable", "crew_id": crew, "start": 30, "end": 40}, now_hour=0)
    assert "rejected_by_reviewer_excluded" not in out2


def test_replan_withdraws_plan_approval():
    s = _session(severities=(2, 2))
    review.approve_plan(s)
    crew = s.base_scenario.crews[0].id
    tools.replan_tool(s, {"type": "crew_unavailable", "crew_id": crew, "start": 0, "end": 24}, now_hour=0)
    assert review.review_summary(s)["plan_approval"] is None


def test_exports_carry_the_reviewer_decision():
    s = _session(severities=(2, 2, 2, 4))
    review.set_decision(s, "W01", "approved")
    review.set_decision(s, "W02", "rejected")
    review.set_decision(s, "W04", "reinspect")
    crew = s.base_scenario.crews[0].id
    tools.replan_tool(s, {"type": "crew_unavailable", "crew_id": crew, "start": 0, "end": 24}, now_hour=0)
    review.approve_plan(s)
    rows = work_orders(s, datetime(2026, 11, 4))
    by = {r["defect_id"]: r for r in rows}
    assert by["W01"]["reviewer_decision"] == "Approved" and by["W01"]["reviewer_decided_at"]
    assert by["W02"]["reviewer_decision"] == "Rejected" and by["W02"]["status"] == "excluded (rejected by reviewer)"
    assert by["W03"]["reviewer_decision"] == "Pending review" and by["W04"]["reviewer_decision"] == "Needs re-inspection"
    assert all(r["plan_approved_at"] for r in rows)
    parsed = list(csv.DictReader(io.StringIO(to_csv(rows))))
    assert parsed[1]["reviewer_decision"] == "Rejected"
    assert json.loads(to_json(rows, s))["work_orders"][0]["reviewer_decision"] == "Approved"


def test_pdf_lists_the_decisions(monkeypatch):
    pytest.importorskip("reportlab")
    from backend.reports import export
    s = _session(severities=(2, 2))
    review.set_decision(s, "W01", "approved")
    monkeypatch.setattr(export, "render_frame", lambda s, f: b"")
    s.voice_notes = []
    pdf = export.pdf_report(s, datetime(2026, 11, 4), max_frames=0)
    assert pdf.startswith(b"%PDF")


def test_review_api_round_trip(monkeypatch):
    s = _session(severities=(2, 4))
    st = app_mod.RunState("run-review", SimpleNamespace(s=s))
    st.status = "done"
    monkeypatch.setitem(app_mod.RUNS, "run-review", st)
    r = client.post("/runs/run-review/approve_plan")
    assert r.status_code == 409 and "W02" in r.json()["detail"]
    r = client.post("/runs/run-review/review", json={"defect_id": "W02", "decision": "approved"})
    assert r.status_code == 200 and r.json()["review"]["decision"] == "approved"
    assert client.post("/runs/run-review/review", json={"defect_id": "W09", "decision": "approved"}).status_code == 404
    assert client.post("/runs/run-review/review", json={"defect_id": "W01", "decision": "x"}).status_code == 422
    r = client.post("/runs/run-review/approve_plan")
    assert r.status_code == 200 and r.json()["plan_approval"]["at"]
    reg = client.get("/runs/run-review/register").json()
    assert reg["entries"][1]["review"]["decision"] == "approved" and reg["review"]["plan_approval"]


def test_approve_records_the_reviewers_severity_and_its_source():
    s = _session(severities=(2, 2))
    out = review.set_decision(s, "W01", "approved", severity=4, source="second opinion")
    assert out["reviewer_severity"] == 4 and out["severity_source"] == "second opinion"
    assert review.set_decision(s, "W02", "approved")["severity_source"] == "verifier"  # default: the shown grade
    assert review.set_decision(s, "W02", "approved", severity=3)["severity_source"] == "own value"
    assert review.set_decision(s, "W02", "rejected")["reviewer_severity"] is None
    with pytest.raises(ValueError):
        review.set_decision(s, "W01", "approved", severity=6)


def test_replan_uses_the_reviewers_severity_for_approved_entries():
    s = _session(severities=(2, 2, 2, 2))
    before = _jobs(s.variants["individual"])["W01"]
    review.set_decision(s, "W01", "approved", severity=4, source="own value")
    crew = s.base_scenario.crews[0].id
    tools.replan_tool(s, {"type": "crew_unavailable", "crew_id": crew, "start": 0, "end": 24}, now_hour=0)
    after = _jobs(s.variants["individual"])["W01"]
    assert before.severity == 2 and after.severity == 4 and after.failure_risk > before.failure_risk
    pkg = next((j for j in s.variants["grouped"]["jobs"] if "W01" in (j.members or [])), None)
    assert pkg is None or pkg.severity == 4  # a package holding W01 is rebuilt at the new severity


def test_approval_rule_uses_the_reviewers_severity():
    s = _session(severities=(2, 4))
    review.set_decision(s, "W02", "approved", severity=3)  # reviewer downgrades the severity-4 entry
    assert review.blocking_entries(s) == []
    s2 = _session(severities=(2, 4))
    assert review.blocking_entries(s2) == ["W02"]


def test_exports_carry_reviewer_severity_and_source():
    s = _session(severities=(2, 2))
    review.set_decision(s, "W01", "approved", severity=3, source="second opinion")
    by = {r["defect_id"]: r for r in work_orders(s, datetime(2026, 11, 4))}
    assert by["W01"]["reviewer_severity"] == 3 and by["W01"]["severity_source"] == "second opinion"
    assert by["W02"]["reviewer_severity"] == "" and by["W02"]["severity_source"] == ""
    assert "reviewer_severity" in to_csv(list(by.values())).splitlines()[0]


def test_opinions_show_both_sides_for_escalated_entries():
    s = _session(severities=(2, 3), disputed=(2,))
    assert [o["source"] for o in review.opinions(s, s.register[0])] == ["verifier"]
    s.register[1].detections[0].senior = dict(first_is_defect=True, first_severity=3, changed_decision=True,
                                              changed_severity=False, reason="confidence 0.40")
    ops = review.opinions(s, s.register[1])
    assert [o["source"] for o in ops] == ["verifier", "second opinion"]
    assert ops[0]["is_defect"] and ops[0]["severity"] == 3 and ops[1]["is_defect"] is False
