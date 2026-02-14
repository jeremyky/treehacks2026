"""
Medical report to command center: build MedicalReport from session/observations, render Markdown.
Open Evidence style: every claim cites evidence_ids. Optional PDF if util exists (none in repo → skip).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from himpublic.medical.report_schema import (
    IncidentMeta,
    LocationAccess,
    PatientSummary,
    ABCDEFinding,
    ABCDEChecklist,
    SuspectedInjury,
    HazardNearby,
    MediaEvidence,
    MediaImage,
    MediaAudio,
    EvidenceItem,
    UncertaintyItem,
    RecommendedNextAction,
    MedicalReport,
    ReportConfig,
)
from himpublic.evidence.evidence_log import EvidenceLog


def _confidence_word(conf: float, config: ReportConfig) -> str:
    if conf >= config.confidence_likely_threshold:
        return "likely"
    if conf >= config.confidence_possible_threshold:
        return "possible"
    return "uncertain"


def _cite(evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return ""
    return " " + " ".join(f"[{eid}]" for eid in evidence_ids)


def render_medical_report_md(
    report: MedicalReport,
    config: ReportConfig,
    image_base_path: str | None = None,
) -> str:
    """
    Produce a single Markdown string for the medical report.
    Uses relative paths for images when image_base_path is set.
    """
    lines: list[str] = []
    prefix = (image_base_path or "").rstrip("/")
    if prefix:
        prefix = prefix + "/"
    meta = report.meta

    # --- A) Header / Incident Meta ---
    lines.append("# Medical / SAR Incident Report")
    lines.append("")
    lines.append("## Incident Meta")
    lines.append(f"- **Report ID:** {meta.report_id}")
    lines.append(f"- **Session ID:** {meta.session_id}")
    lines.append(f"- **Timestamp range:** {meta.timestamp_start:.0f} – {meta.timestamp_end:.0f} ({meta.timezone})")
    if meta.robot_id:
        lines.append(f"- **Robot:** {meta.robot_id}")
    if meta.operator_id:
        lines.append(f"- **Operator:** {meta.operator_id}")
    if meta.environment_label:
        lines.append(f"- **Environment:** {meta.environment_label}")
    lines.append("")

    # --- B) Location & Access ---
    lines.append("## Location & Access")
    if report.location_access:
        loc = report.location_access
        lines.append(f"- **Best-known location:** {loc.location_estimate or '—'}")
        if loc.coordinates:
            lines.append(f"- **Coordinates:** {loc.coordinates}")
        if loc.location_derivation:
            lines.append(f"- **Derivation:** {loc.location_derivation}{_cite(loc.evidence_ids)}")
        if loc.access_constraints:
            lines.append("- **Access constraints:** " + "; ".join(loc.access_constraints))
        if loc.suggested_approach_route:
            lines.append(f"- **Suggested approach:** {loc.suggested_approach_route}")
    else:
        lines.append("*No location data.*")
    lines.append("")

    # --- C) Patient Summary ---
    lines.append("## Patient Summary")
    if report.patient_summary:
        ps = report.patient_summary
        if ps.one_liner:
            lines.append(ps.one_liner)
        if ps.estimated_age_range or ps.estimated_sex:
            parts = []
            if ps.estimated_age_range:
                parts.append(f"Estimated age: {ps.estimated_age_range}")
            if ps.estimated_sex:
                parts.append(f"Estimated sex: {ps.estimated_sex}")
            lines.append("(" + "; ".join(parts) + ")")
        lines.append(f"- **Consciousness:** {ps.consciousness or '—'}")
        lines.append(f"- **Primary concern:** {ps.primary_concern or '—'}{_cite(ps.evidence_ids)}")
        lines.append(f"- **Triage category:** {ps.triage_category or '—'}")
        lines.append(f"- **Overall confidence:** {ps.overall_confidence:.2f} — {ps.confidence_explanation or '—'}")
    else:
        lines.append("*No patient summary.*")
    lines.append("")

    # --- D) Findings: ABCDE ---
    lines.append("## ABCDE Findings")
    if report.abcde:
        abcd = report.abcde
        lines.append("| Component | Status | Evidence | Confidence | Notes |")
        lines.append("|----------|--------|----------|------------|-------|")
        for name, finding in [
            ("Airway", abcd.airway),
            ("Breathing", abcd.breathing),
            ("Circulation", abcd.circulation),
            ("Disability", abcd.disability),
            ("Exposure", abcd.exposure),
        ]:
            refs = ", ".join(finding.evidence_ids) if finding.evidence_ids else "—"
            lines.append(f"| {name} | {finding.status} | {refs} | {finding.confidence:.2f} | {finding.notes or '—'} |")
    else:
        lines.append("*No ABCDE checklist.*")
    lines.append("")

    # --- D) Suspected Injuries ---
    lines.append("## Suspected Injuries")
    if report.suspected_injuries:
        lines.append("| Type | Body location | Severity | Confidence | Rationale | Evidence |")
        lines.append("|------|----------------|----------|------------|-----------|----------|")
        for i in report.suspected_injuries:
            refs = ", ".join(i.evidence_ids) if i.evidence_ids else "—"
            lines.append(f"| {i.injury_type} | {i.body_location} | {i.severity_estimate} | {i.confidence:.2f} | {i.rationale or '—'} | {refs} |")
        for i in report.suspected_injuries:
            if i.immediate_actions_recommended:
                lines.append(f"- **{i.body_location}:** " + "; ".join(i.immediate_actions_recommended))
    else:
        lines.append("*No suspected injuries.*")
    lines.append("")

    # --- D) Hazards ---
    lines.append("## Hazards Nearby")
    if report.hazards_nearby:
        lines.append("| Description | Risk level | Evidence |")
        lines.append("|-------------|------------|----------|")
        for h in report.hazards_nearby:
            refs = ", ".join(h.evidence_ids) if h.evidence_ids else "—"
            lines.append(f"| {h.description} | {h.risk_level} | {refs} |")
    else:
        lines.append("*No hazards recorded.*")
    lines.append("")

    # --- E) Media Evidence ---
    lines.append("## Media Evidence")
    if report.media:
        m = report.media
        def _img_ref(img: MediaImage) -> str:
            if not img.file_path:
                return img.evidence_id
            if prefix and not img.file_path.startswith(prefix.rstrip("/") + "/") and not img.file_path.startswith(prefix):
                return f"{prefix}{img.file_path}"
            return img.file_path

        if m.scene_overview_images:
            lines.append("### Scene Overview")
            for img in m.scene_overview_images[: config.max_images_per_section]:
                ref = _img_ref(img)
                lines.append(f"- **{img.evidence_id}** — {img.caption or ref} (t={img.timestamp:.0f})")
                if ref and not ref.startswith("http"):
                    lines.append(f"  ![]({ref})")
        if m.injury_closeup_images:
            lines.append("### Injury Close-ups")
            for img in m.injury_closeup_images[: config.max_images_per_section]:
                ref = _img_ref(img)
                lines.append(f"- **{img.evidence_id}** — {img.caption or ref} (t={img.timestamp:.0f})")
                if ref and not ref.startswith("http"):
                    lines.append(f"  ![]({ref})")
        if m.audio:
            lines.append("### Audio")
            for a in m.audio:
                snippet = a.transcript_snippet[:200] + "…" if len(a.transcript_snippet) > 200 else a.transcript_snippet
                lines.append(f"- **{a.evidence_id}** (t={a.timestamp:.0f}, conf={a.confidence:.2f}): {snippet or '—'}")
                if config.include_raw_transcripts and a.file_path:
                    lines.append(f"  *File:* {a.file_path}")
    else:
        lines.append("*No media evidence.*")
    lines.append("")

    # --- F) Evidence & Provenance ---
    lines.append("## Evidence & Provenance")
    if report.evidence_items:
        lines.append("| evidence_id | type | timestamp | source | file_path | confidence | summary |")
        lines.append("|-------------|------|-----------|--------|-----------|------------|--------|")
        for e in report.evidence_items:
            lines.append(f"| {e.evidence_id} | {e.type} | {e.timestamp:.0f} | {e.source} | {e.file_path or '—'} | {e.confidence:.2f} | {e.summary[:50] + '…' if len(e.summary) > 50 else e.summary or '—'} |")
    else:
        lines.append("*No evidence log.*")
    lines.append("")

    # --- G) Uncertainty ---
    lines.append("## Uncertainty / Assumptions")
    if report.uncertainties:
        for u in report.uncertainties:
            lines.append(f"- **{u.item}** — {u.reason}")
            if u.alternative_hypotheses:
                lines.append(f"  Alternatives: {'; '.join(u.alternative_hypotheses)}")
    else:
        lines.append("*None recorded.*")
    lines.append("")

    # --- H) Recommended Next Actions ---
    lines.append("## Recommended Next Actions (Command Center)")
    if report.recommended_actions:
        for i, a in enumerate(report.recommended_actions[:5], 1):
            warn = " **[SAFETY WARNING]**" if a.safety_warning else ""
            lines.append(f"{i}. [{a.urgency or '—'}] {a.action}{warn}")
    else:
        lines.append("*None specified.*")
    lines.append("")

    # --- I) Disclaimer ---
    lines.append("---")
    lines.append("")
    lines.append("*Automated preliminary assessment. Not a medical diagnosis. Confirm by qualified responder.*")
    lines.append("")

    return "\n".join(lines)


def build_medical_report_from_observations(
    session_ctx: dict[str, Any],
    observations: dict[str, Any],
    images: list[dict[str, Any]] | list[str],
    audio: list[dict[str, Any]] | None,
    model_outputs: dict[str, Any] | None,
    evidence_log: EvidenceLog | None,
) -> MedicalReport:
    """
    Build a MedicalReport from dict-like session_ctx, observations, images, audio, model_outputs.
    If evidence_log is provided, images/audio are registered and get evidence_ids.
    """
    model_outputs = model_outputs or {}
    observations = observations or {}
    session_ctx = session_ctx or {}

    report_id = session_ctx.get("report_id") or f"report_{int(time.time() * 1000)}"
    session_id = session_ctx.get("session_id") or report_id
    ts_start = session_ctx.get("timestamp_start", time.time() - 60)
    ts_end = session_ctx.get("timestamp_end", time.time())

    meta = IncidentMeta(
        report_id=report_id,
        session_id=session_id,
        timestamp_start=ts_start,
        timestamp_end=ts_end,
        timezone=session_ctx.get("timezone", "UTC"),
        robot_id=session_ctx.get("robot_id", ""),
        operator_id=session_ctx.get("operator_id", ""),
        environment_label=session_ctx.get("environment_label", ""),
    )

    # Location
    loc_data = observations.get("location") or observations.get("location_access") or {}
    if isinstance(loc_data, dict):
        location_access = LocationAccess(
            location_estimate=loc_data.get("location_estimate", observations.get("location_estimate", "")),
            coordinates=loc_data.get("coordinates", observations.get("coordinates", "")),
            location_derivation=loc_data.get("location_derivation", observations.get("location_derivation", "")),
            access_constraints=loc_data.get("access_constraints", observations.get("access_constraints", [])),
            suggested_approach_route=loc_data.get("suggested_approach_route", observations.get("suggested_approach_route", "")),
            evidence_ids=loc_data.get("evidence_ids", []),
        )
    else:
        location_access = None

    # Patient summary
    ps_data = observations.get("patient_summary") or observations
    patient_summary = PatientSummary(
        one_liner=ps_data.get("one_liner", observations.get("patient_one_liner", "")),
        estimated_age_range=ps_data.get("estimated_age_range", ""),
        estimated_sex=ps_data.get("estimated_sex", ""),
        consciousness=ps_data.get("consciousness", observations.get("consciousness", "")),
        primary_concern=ps_data.get("primary_concern", observations.get("primary_concern", "")),
        triage_category=ps_data.get("triage_category", observations.get("triage_category", "")),
        overall_confidence=float(ps_data.get("overall_confidence", observations.get("overall_confidence", 0))),
        confidence_explanation=ps_data.get("confidence_explanation", observations.get("confidence_explanation", "")),
        evidence_ids=ps_data.get("evidence_ids", []),
    )

    # ABCDE
    abcde_data = observations.get("abcde") or {}
    if abcde_data:
        def _ab(s: str) -> ABCDEFinding:
            d = abcde_data.get(s, {}) if isinstance(abcde_data.get(s), dict) else {}
            return ABCDEFinding(
                status=d.get("status", ""),
                evidence_ids=d.get("evidence_ids", []),
                confidence=float(d.get("confidence", 0)),
                notes=d.get("notes", ""),
            )
        abcde = ABCDEChecklist(
            airway=_ab("airway"),
            breathing=_ab("breathing"),
            circulation=_ab("circulation"),
            disability=_ab("disability"),
            exposure=_ab("exposure"),
        )
    else:
        abcde = None

    # Suspected injuries
    injuries_data = observations.get("suspected_injuries") or observations.get("injuries") or []
    suspected_injuries = []
    for inj in injuries_data:
        if isinstance(inj, dict):
            suspected_injuries.append(SuspectedInjury(
                injury_type=inj.get("injury_type", inj.get("type", "")),
                body_location=inj.get("body_location", inj.get("body_region", "")),
                severity_estimate=inj.get("severity_estimate", inj.get("severity", "")),
                confidence=float(inj.get("confidence", 0)),
                rationale=inj.get("rationale", ""),
                immediate_actions_recommended=inj.get("immediate_actions_recommended", inj.get("actions", [])),
                evidence_ids=inj.get("evidence_ids", []),
            ))
        else:
            suspected_injuries.append(SuspectedInjury())

    # Hazards
    hazards_data = observations.get("hazards_nearby") or observations.get("hazards") or []
    hazards_nearby = []
    for h in hazards_data:
        if isinstance(h, dict):
            hazards_nearby.append(HazardNearby(
                description=h.get("description", h.get("type", "")),
                risk_level=h.get("risk_level", h.get("severity", "")),
                evidence_ids=h.get("evidence_ids", []),
            ))
        else:
            hazards_nearby.append(HazardNearby(description=str(h)))

    # Media: images + audio (optionally register with evidence_log)
    scene_images: list[MediaImage] = []
    injury_images: list[MediaImage] = []
    audio_list: list[MediaAudio] = []

    def _norm_images(imgs: list[dict[str, Any]] | list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for x in imgs or []:
            if isinstance(x, str):
                out.append({"file_path": x, "section": "scene_overview", "caption": ""})
            else:
                out.append(x)
        return out

    for img in _norm_images(images or [])[: 2 * 10]:  # cap total
        path = img.get("file_path", img.get("path", ""))
        section = img.get("section", "scene_overview")
        caption = img.get("caption", img.get("description", ""))
        ts = float(img.get("timestamp", time.time()))
        evidence_id = img.get("evidence_id", "")
        if evidence_log and not evidence_id:
            evidence_id = evidence_log.add_evidence(
                type="image",
                source=img.get("source", "camera"),
                timestamp=ts,
                file_path=path,
                confidence=float(img.get("confidence", 0)),
                summary=caption or path,
            )
        mi = MediaImage(file_path=path, timestamp=ts, caption=caption, evidence_id=evidence_id, section=section)
        if section == "injury_closeup":
            injury_images.append(mi)
        else:
            scene_images.append(mi)

    for a in (audio or [])[: 5]:
        if isinstance(a, dict):
            path = a.get("file_path", a.get("path", ""))
            snippet = a.get("transcript_snippet", a.get("transcript", ""))
            ts = float(a.get("timestamp", time.time()))
            evidence_id = a.get("evidence_id", "")
            if evidence_log and not evidence_id:
                evidence_id = evidence_log.add_evidence(
                    type="audio",
                    source=a.get("source", "mic"),
                    timestamp=ts,
                    file_path=path,
                    confidence=float(a.get("confidence", 0)),
                    summary=snippet[:200] if snippet else path,
                )
            audio_list.append(MediaAudio(
                file_path=path,
                transcript_snippet=snippet,
                timestamp=ts,
                evidence_id=evidence_id,
                confidence=float(a.get("confidence", 0)),
            ))
        else:
            audio_list.append(MediaAudio())

    media = MediaEvidence(
        scene_overview_images=scene_images,
        injury_closeup_images=injury_images,
        audio=audio_list,
    ) if (scene_images or injury_images or audio_list) else None

    # Evidence items from log
    evidence_items = evidence_log.to_evidence_items() if evidence_log else []

    # Uncertainties
    unc_data = observations.get("uncertainties") or observations.get("uncertainty") or []
    uncertainties = []
    for u in unc_data:
        if isinstance(u, dict):
            uncertainties.append(UncertaintyItem(
                item=u.get("item", ""),
                reason=u.get("reason", ""),
                alternative_hypotheses=u.get("alternative_hypotheses", []),
            ))
        else:
            uncertainties.append(UncertaintyItem(item=str(u), reason=""))

    # Recommended actions
    actions_data = observations.get("recommended_actions") or model_outputs.get("recommended_actions") or []
    recommended_actions = []
    for ra in actions_data[:5]:
        if isinstance(ra, dict):
            recommended_actions.append(RecommendedNextAction(
                action=ra.get("action", ra.get("text", "")),
                urgency=ra.get("urgency", ra.get("priority", "")),
                safety_warning=bool(ra.get("safety_warning", False)),
            ))
        elif isinstance(ra, str):
            recommended_actions.append(RecommendedNextAction(action=ra))

    return MedicalReport(
        meta=meta,
        location_access=location_access,
        patient_summary=patient_summary,
        abcde=abcde,
        suspected_injuries=suspected_injuries,
        hazards_nearby=hazards_nearby,
        media=media,
        evidence_items=evidence_items,
        uncertainties=uncertainties,
        recommended_actions=recommended_actions,
    )


def generate_medical_report(
    session_ctx: dict[str, Any],
    observations: dict[str, Any],
    images: list[dict[str, Any]] | list[str],
    audio: list[dict[str, Any]] | None = None,
    model_outputs: dict[str, Any] | None = None,
    artifact_paths: dict[str, str] | None = None,
    config: ReportConfig | None = None,
) -> tuple[str, str | None]:
    """
    Build medical report from session/observations, write Markdown to sessions/<session_id>/reports/medical_report.md.
    Returns (report_md_path, optional_pdf_path). PDF is not implemented (no PDF util in repo); second value is always None.
    Orchestrator can call:
      from himpublic.reporting.render_medical_report import generate_medical_report
      md_path, pdf_path = generate_medical_report(session_ctx, observations, images, audio, model_outputs, artifact_paths)
    """
    config = config or ReportConfig()
    artifact_paths = artifact_paths or {}
    session_id = (session_ctx or {}).get("session_id") or (session_ctx or {}).get("report_id") or "default"
    base_dir = artifact_paths.get("sessions_base", "artifacts/sessions")
    sessions_root = Path(base_dir)
    session_dir = sessions_root / session_id
    reports_dir = session_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    evidence_log_path = session_dir / "evidence.jsonl"
    evidence_log = EvidenceLog(evidence_log_path)

    report = build_medical_report_from_observations(
        session_ctx=session_ctx or {},
        observations=observations or {},
        images=images or [],
        audio=audio,
        model_outputs=model_outputs,
        evidence_log=evidence_log,
    )

    image_base = artifact_paths.get("images_relative", "images")
    md_content = render_medical_report_md(report, config, image_base_path=image_base)

    report_md_path = reports_dir / "medical_report.md"
    report_md_path.write_text(md_content, encoding="utf-8")

    pdf_path: str | None = None
    if config.include_pdf:
        # No PDF util in repo; leave as None. Could add weasyprint/reportlab later.
        pass

    return str(report_md_path), pdf_path


def assign_image_captions_and_evidence(
    image_paths: list[str],
    evidence_log: EvidenceLog,
    section: str = "scene_overview",
    captions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Helper: given list of image file paths, register each in evidence_log and return
    list of dicts with file_path, evidence_id, caption, section, timestamp for report.
    """
    now = time.time()
    captions = captions or []
    out: list[dict[str, Any]] = []
    for i, path in enumerate(image_paths):
        caption = captions[i] if i < len(captions) else Path(path).name
        eid = evidence_log.add_evidence(
            type="image",
            source="camera",
            timestamp=now,
            file_path=path,
            confidence=0.0,
            summary=caption,
        )
        out.append({
            "file_path": path,
            "evidence_id": eid,
            "caption": caption,
            "section": section,
            "timestamp": now,
        })
    return out
