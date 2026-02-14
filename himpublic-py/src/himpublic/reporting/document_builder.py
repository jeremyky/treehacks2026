"""Document builder: IncidentReport -> command-center readable Markdown with embedded image refs."""

from __future__ import annotations

from .types import IncidentReport, ImageEvidence


def build_markdown(report: IncidentReport, image_base_path: str | None = None) -> str:
    """
    Generate report.md with: Situation Summary, Location & Access, Victim Status,
    Injuries (table), Hazards/Debris, Evidence Images, Recommended Actions, Confidence & Limitations.
    image_base_path: if set, image refs use this prefix (e.g. "images/") for relative paths.
    """
    lines: list[str] = []
    prefix = (image_base_path or "").rstrip("/")
    if prefix:
        prefix = prefix + "/"

    # Title
    lines.append(f"# Incident Report: {report.incident_id}")
    lines.append("")

    # Situation Summary
    lines.append("## Situation Summary")
    lines.append(f"- **Incident ID:** {report.incident_id}")
    lines.append(f"- **Time:** {report.timestamp_start:.0f} – {report.timestamp_end:.0f}")
    lines.append(f"- **Robot:** {report.robot_id}")
    if report.operator:
        lines.append(f"- **Operator:** {report.operator}")
    if report.medical_chatbot:
        lines.append(f"- **Triage:** {report.medical_chatbot.triage_priority} (confidence: {report.medical_chatbot.overall_confidence:.2f})")
    lines.append("")

    # Location & Access
    lines.append("## Location & Access")
    if report.location:
        loc = report.location
        lines.append(f"- **Frame:** {loc.frame}  **Position:** ({loc.x:.2f}, {loc.y:.2f}) yaw={loc.yaw:.2f}")
        if loc.floor:
            lines.append(f"- **Floor:** {loc.floor}")
        if loc.area_label:
            lines.append(f"- **Area:** {loc.area_label}")
        lines.append(f"- **Approach path:** {loc.approach_path_status}")
        if loc.nav_notes:
            lines.append(f"- **Nav notes:** {loc.nav_notes}")
        lines.append(f"- **Confidence:** {loc.confidence:.2f}")
    else:
        lines.append("*No location data.*")
    lines.append("")

    # Victim Status
    lines.append("## Victim Status")
    if report.victim:
        v = report.victim
        lines.append(f"- **Victim ID:** {v.victim_id}")
        lines.append(f"- **Detection:** confidence={v.detection.confidence:.2f}, method={v.detection.method}")
        lines.append(f"- **Responsiveness:** {v.responsiveness}")
        lines.append(f"- **Breathing:** {v.breathing}  **Mobility:** {v.mobility}")
    else:
        lines.append("*No victim summary.*")
    lines.append("")

    # Injuries (table)
    lines.append("## Injuries")
    if report.injuries:
        lines.append("| Type | Body region | Severity | Confidence | Evidence images |")
        lines.append("|------|-------------|----------|-------------|-----------------|")
        for i in report.injuries:
            imgs = ", ".join(i.evidence_image_ids) if i.evidence_image_ids else "—"
            lines.append(f"| {i.type} | {i.body_region} | {i.severity} | {i.confidence:.2f} | {imgs} |")
    else:
        lines.append("*No injury findings.*")
    lines.append("")

    # Hazards / Debris
    lines.append("## Hazards & Debris")
    if report.hazards_debris:
        hd = report.hazards_debris
        if hd.hazards:
            lines.append("**Hazards:**")
            for h in hd.hazards:
                lines.append(f"- {h.type} (severity={h.severity}, conf={h.confidence:.2f}) {h.notes or ''}")
        if hd.debris:
            lines.append("**Debris:**")
            for d in hd.debris:
                pose = f" @ ({d.pose[0]:.2f},{d.pose[1]:.2f})" if d.pose else ""
                lines.append(f"- {d.type} movable={d.movable}{pose} (conf={d.confidence:.2f}) {d.notes or ''}")
        if hd.recommended_tools:
            lines.append(f"**Recommended tools:** {', '.join(hd.recommended_tools)}")
    else:
        lines.append("*No hazards or debris.*")
    lines.append("")

    # Medical Chatbot
    if report.medical_chatbot:
        mc = report.medical_chatbot
        lines.append("## Medical Chatbot")
        lines.append(mc.chatbot_summary)
        lines.append("")
        lines.append(f"**Triage priority:** {mc.triage_priority}  **Confidence:** {mc.overall_confidence:.2f}")
        if mc.triage_rationale:
            lines.append("**Rationale:**")
            for r in mc.triage_rationale:
                lines.append(f"- {r.claim} — *{r.evidence}*")
        if mc.questions_asked and mc.answers:
            lines.append("**Q&A:**")
            for i, q in enumerate(mc.questions_asked):
                a = mc.answers[i].answer if i < len(mc.answers) else "(no answer)"
                lines.append(f"- Q: {q.question}")
                lines.append(f"  A: {a}")
    lines.append("")

    # Evidence Images (embedded refs)
    lines.append("## Evidence Images")
    if report.images:
        for img in report.images:
            ref = f"{prefix}{img.path}" if img.path else img.image_id
            lines.append(f"- **{img.image_id}** ({img.kind}): {img.description or ref}")
            if ref and not ref.startswith("http"):
                lines.append(f"  ![]({ref})")
    else:
        lines.append("*No images.*")
    lines.append("")

    # Recommended Actions
    lines.append("## Recommended Actions")
    if report.recommended_actions and getattr(report.recommended_actions, "recommended_actions", None):
        for a in report.recommended_actions.recommended_actions:
            lines.append(f"- [{a.priority}] {a.action} — {a.why}")
    else:
        lines.append("*None specified.*")
    lines.append("")

    # Confidence & Limitations
    lines.append("## Confidence & Limitations")
    if report.medical_chatbot:
        lines.append(f"- Overall triage confidence: {report.medical_chatbot.overall_confidence:.2f}")
    if report.comms_status:
        lines.append(f"- Comms: sent={report.comms_status.sent}, endpoint={report.comms_status.endpoint or 'N/A'}")
        if report.comms_status.error:
            lines.append(f"  Error: {report.comms_status.error}")
    lines.append("")

    return "\n".join(lines)
