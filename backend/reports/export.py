"""F8 exports: inspection report (PDF) and CMMS-style work orders (CSV / JSON).

Work orders use a generic, CMMS-compatible flat format (one row per walkdown defect: priority, asset, action,
crew, planned start/end, permit, shutdown need, status). It is a compatible format for import, not a certified
integration with any CMMS product. Every work order is marked "approval required": Walkdown is decision
support and never issues work itself.

Hours in the plan count from the plan start; ``plan_start`` (ISO date-time) turns them into timestamps.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

PRIORITY = {5: "P1-emergency", 4: "P2-urgent", 3: "P3-planned", 2: "P4-routine", 1: "P5-monitor"}
FIELDS = ["work_order_id", "defect_id", "priority", "asset_tag", "asset_type", "location", "line_service",
          "defect_type", "severity", "confidence", "recommended_action", "required_skill", "repair_hours",
          "needs_shutdown", "permit", "status", "crew", "planned_start", "planned_end", "plan_status", "plan_gap",
          "needs_review", "senior_review", "evidence", "approval_required", "source"]


def _when(plan_start: datetime, hour: int | None) -> str:
    return "" if hour is None else (plan_start + timedelta(hours=hour)).isoformat(timespec="minutes")


def work_orders(s, plan_start: datetime) -> list[dict]:
    """One work order per register entry, joined with its plan assignment and planner defect."""
    defects = {d.id: d for d in (s.scenario.defects if s.scenario else [])}
    assign = {a.defect_id: a for a in (s.plan.assignments if s.plan else [])}
    rows = []
    for i, e in enumerate(s.register):
        g, d, a = e.grade, defects.get(e.defect_id), assign.get(e.defect_id)
        senior = next((x.senior for x in e.detections if x.senior), None)
        rows.append(dict(
            work_order_id=f"WD-{e.asset.asset_id}-{i + 1:03d}", defect_id=e.defect_id, priority=PRIORITY[g.severity],
            asset_tag=e.asset.asset_id, asset_type=e.asset.asset_type, location=g.evidence.location or e.asset.location,
            line_service=e.asset.service or "", defect_type=g.defect_type.value, severity=g.severity,
            confidence=round(g.confidence, 2), recommended_action=g.recommended_action.value,
            required_skill=d.skill if d else "", repair_hours=d.repair_hours if d else "",
            needs_shutdown=bool(d and d.needs_shutdown), permit=(d.permit or "") if d else "",
            status="planned" if a else ("unscheduled" if s.plan else "not planned"),
            crew=a.crew_id if a else "", planned_start=_when(plan_start, a.start if a else None),
            planned_end=_when(plan_start, a.end if a else None),
            plan_status=s.plan.stats.status if s.plan else "", plan_gap=(
                "" if not s.plan or s.plan.stats.gap is None else round(s.plan.stats.gap, 4)),
            needs_review=e.needs_review,
            senior_review=("" if not senior else (("disputed, needs human review" if senior["first_is_defect"] else "accepted first-pass rejection")
                           if senior["changed_decision"] else
                           f"severity {senior['first_severity']}->{g.severity}" if senior["changed_severity"] else "confirmed")),
            evidence="; ".join(g.evidence.visual_cues[:3]), approval_required=True,
            source="Walkdown (decision support; requires approval by a qualified person)"))
    return rows


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def to_json(rows: list[dict], s) -> str:
    return json.dumps(dict(format="walkdown-work-orders/v1", note="CMMS-compatible format; not a certified integration",
                           asset=s.clip.asset.__dict__, work_orders=rows), indent=1)


def render_frame(s, frame: int) -> bytes:
    """One frame with every register detection outlined, coloured by severity, and labelled (JPEG)."""
    import cv2
    colours = {1: (120, 200, 120), 2: (60, 200, 230), 3: (40, 160, 255), 4: (40, 90, 255), 5: (60, 40, 230)}
    img = cv2.imread(str(s.frame_paths[frame]), cv2.IMREAD_COLOR)
    for e in s.register:
        for d in e.detections:
            if d.frame != frame:
                continue
            _, inst = s.candidates[d.candidate_id]
            colour = colours[d.grade.severity]
            contours, _ = cv2.findContours(inst.mask.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            overlay = img.copy()
            cv2.drawContours(overlay, contours, -1, colour, -1)
            img = cv2.addWeighted(overlay, 0.25, img, 0.75, 0)
            cv2.drawContours(img, contours, -1, colour, 2)
            l, t = d.box[0], max(14, d.box[1] - 4)
            cv2.putText(img, f"{e.defect_id} S{d.grade.severity}", (l, t), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes()


SAFE_USE = ("Decision support only. Walkdown never operates or controls plant equipment; every repair, isolation "
            "and shutdown needs approval by a qualified person. It misses corrosion and flags things that are not "
            "corrosion; severity grades are consistency-checked, not accuracy-validated. Not a substitute for "
            "certified inspection programmes (API 570 / 510 / 653, RBI).")


def pdf_report(s, plan_start: datetime, *, max_frames: int = 6) -> bytes:
    """Inspection report: summary, safe-use notice, register, frames with outlines, work orders, plan reasons."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=8, leading=10)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"Walkdown inspection report {s.clip.asset.asset_id}")
    a = s.clip.asset
    story = [Paragraph(f"Walkdown inspection report · {escape(a.asset_id)}", st["Title"]),
             Paragraph(f"Asset type {escape(a.asset_type)}; service {a.service or 'unknown'}; location {escape(a.location or '-')}; "
                       f"plan start {plan_start.isoformat(timespec='minutes')}. Generated by Walkdown "
                       f"(built with Muse Spark Open; hosted models via the Meta Model API).", small),
             Spacer(1, 4), Paragraph(f"<b>Safe use.</b> {SAFE_USE}", small), Spacer(1, 6)]
    if s.plan:
        stats = s.plan.stats
        story.append(Paragraph(
            f"<b>Plan</b>: solver status {stats.status}"
            + ("" if stats.gap is None else f", optimality gap {100 * stats.gap:.1f}%")
            + (" (FEASIBLE: not proven optimal)" if stats.status == "FEASIBLE" else "")
            + f"; {len(s.plan.assignments)} jobs scheduled, {len(s.plan.unscheduled)} unscheduled.", st["BodyText"]))
    story.append(Paragraph(f"<b>Register</b>: {len(s.register)} defects; "
                           f"{sum(e.needs_review for e in s.register)} need human review.", st["BodyText"]))

    rows = work_orders(s, plan_start)
    head = ["WO", "Defect", "Priority", "Type", "Sev", "Action", "Crew", "Start", "End", "Status", "Review"]
    data = [head] + [[r["work_order_id"], r["defect_id"], r["priority"], r["defect_type"].replace("_", " "),
                      r["severity"], r["recommended_action"].replace("_", " "), r["crew"], r["planned_start"],
                      r["planned_end"], r["status"],
                      ", ".join(x for x in (("review" if r["needs_review"] else ""), r["senior_review"] and
                                            f"senior: {r['senior_review']}") if x)] for r in rows]
    table = Table([[Paragraph(escape(str(c)), small) for c in row] for row in data], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e9ec")),
                               ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8bec4")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [Spacer(1, 6), Paragraph("Work orders (proposed; approval required)", st["Heading2"]), table]

    frames = sorted({d.frame for e in s.register for d in e.detections})[:max_frames]
    if frames:
        story += [Spacer(1, 6), Paragraph("Frames with detections (outline colour = severity)", st["Heading2"])]
        imgs = [Image(io.BytesIO(render_frame(s, f)), width=85 * mm, height=64 * mm, kind="proportional") for f in frames]
        story.append(Table([imgs[i:i + 3] for i in range(0, len(imgs), 3)]))

    if s.plan and s.plan.explanations:
        ids = {e.defect_id for e in s.register}
        story += [Spacer(1, 6), Paragraph("Why the plan looks like this (planner reasons)", st["Heading2"])]
        for ex in s.plan.explanations:
            if ex.defect_id in ids:
                reasons = "; ".join(r.code.value if hasattr(r.code, "value") else str(r.code) for r in ex.reasons) or "-"
                story.append(Paragraph(escape(f"{ex.defect_id}: {ex.status}; reasons: {reasons}"), small))
    for n in getattr(s, "voice_notes", []):
        if n.get("note"):
            story += [Spacer(1, 4), Paragraph(f"<b>Inspector voice note</b>: {escape(n['note']['summary'])}", small)]
    doc.build(story)
    return buf.getvalue()
