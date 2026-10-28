"""F8 exports: work-order rows join register and plan; CSV/JSON/PDF render (synthetic frame, no dataset images)."""

import csv
import io
import json
from datetime import datetime
from types import SimpleNamespace

import cv2
import numpy as np

from backend.agent.register import AssetInfo, Detection, RegisterEntry
from backend.perception.sam import Instance
from backend.planner.models import Assignment, Defect
from backend.reports import export
from backend.verify.schema import Grade


def grade(sev):
    return Grade.model_validate({"is_defect": True, "defect_type": "corrosion", "severity": sev, "confidence": 0.77,
                                 "recommended_action": "repair", "evidence": {"visual_cues": ["scale <heavy> & pits"],
                                 "location": "flange", "extent": "small", "mask_fit": "good"}})


def session(tmp_path):
    frame = tmp_path / "f0.jpg"
    cv2.imwrite(str(frame), np.full((120, 160, 3), 128, np.uint8))
    mask = np.zeros((120, 160), bool)
    mask[30:60, 40:90] = True
    asset = AssetInfo(asset_id="P-101", asset_type="pipe", service="lpg")
    reg = [RegisterEntry("W01", asset, [Detection("c1", 0, (40, 30, 90, 60), grade(4), [],
                         {"changed_decision": False, "changed_severity": True, "first_severity": 5})], False),
           RegisterEntry("W02", asset, [Detection("c1", 0, (40, 30, 90, 60), grade(2), ["poor_mask_fit"])], True)]
    defects = [Defect(id="W01", asset="P-101", severity=4, failure_risk=0.5, repair_hours=6, skill="welding",
                      needs_shutdown=True, permit="hot_work"),
               Defect(id="W02", asset="P-101", severity=2, failure_risk=0.2, repair_hours=3, skill="coating")]
    plan = SimpleNamespace(assignments=[Assignment(defect_id="W01", crew_id="C2", start=26, end=32)],
                           unscheduled=["W02"], stats=SimpleNamespace(status="FEASIBLE", gap=0.031), explanations=[])
    inst = Instance(object_id="0", box=(40, 30, 90, 60), mask=mask, confidence=0.9)
    return SimpleNamespace(register=reg, plan=plan, scenario=SimpleNamespace(defects=defects),
                           candidates={"c1": (0, inst)}, frame_paths={0: frame}, voice_notes=[],
                           clip=SimpleNamespace(asset=asset))


def test_work_orders_join_plan_and_register(tmp_path):
    rows = export.work_orders(session(tmp_path), datetime(2026, 11, 2))
    w1, w2 = rows
    assert w1["priority"] == "P2-urgent" and w1["crew"] == "C2" and w1["planned_start"] == "2026-11-03T02:00"
    assert w1["needs_shutdown"] and w1["permit"] == "hot_work" and w1["senior_review"] == "severity 5->4"
    assert w2["status"] == "unscheduled" and w2["crew"] == "" and w2["needs_review"]
    assert all(r["approval_required"] for r in rows) and w1["plan_status"] == "FEASIBLE"


def test_csv_json_and_pdf(tmp_path):
    s = session(tmp_path)
    rows = export.work_orders(s, datetime(2026, 11, 2))
    parsed = list(csv.DictReader(io.StringIO(export.to_csv(rows))))
    assert [r["defect_id"] for r in parsed] == ["W01", "W02"] and list(parsed[0]) == export.FIELDS
    doc = json.loads(export.to_json(rows, s))
    assert doc["format"] == "walkdown-work-orders/v1" and "not a certified" in doc["note"]
    pdf = export.pdf_report(s, datetime(2026, 11, 2))
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    jpg = export.render_frame(s, 0)
    assert jpg[:2] == b"\xff\xd8"
