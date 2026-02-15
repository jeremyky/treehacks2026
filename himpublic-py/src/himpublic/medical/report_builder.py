"""
ReportBuilder — produces a rich Markdown triage report using Jinja2 templates.

Responsibilities:
  1. Load Jinja2 template from ``templates/triage_report.md.j2``
  2. Given a TriageReport, render Markdown with embedded images
  3. Write the report to ``reports/triage_<timestamp>.md``

Also provides helpers to turn findings into narrative sentences and action lines.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .schemas import Finding, RankedSuspectedInjury, TriageReport

logger = logging.getLogger(__name__)

# ── Jinja2 (graceful degrade) ────────────────────────────────────────────
_JINJA_AVAILABLE = False
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    _JINJA_AVAILABLE = True
except ImportError:
    pass


# ── Narrative helpers ────────────────────────────────────────────────────

def finding_to_narrative(finding: Finding, victim_answers: dict[str, str] | None = None) -> str:
    """Turn a single finding into a narrative sentence for the summary."""
    victim_answers = victim_answers or {}
    sentence = (
        f"{finding.confidence_label.capitalize()} {finding.finding_type.replace('suspected_', '')} "
        f"observed near {finding.body_region} (confidence {finding.confidence:.2f})."
    )
    # Append victim info when available
    if finding.finding_type == "suspected_bleeding":
        sev = victim_answers.get("bleed_severity")
        if sev:
            sentence += f" Victim reports {sev} bleeding."
    elif finding.finding_type == "suspected_burn":
        blister = victim_answers.get("burn_blister")
        if blister:
            sentence += f" Victim reports: {blister}."
    return sentence


def finding_to_action(finding: Finding) -> str:
    """Turn a finding into a recommended-action line."""
    if finding.severity == "high" and "bleeding" in finding.finding_type:
        return (
            f"URGENT: Suspected heavy bleeding near {finding.body_region} "
            f"(confidence {finding.confidence:.2f}). "
            "Request immediate responder. Maintain pressure if possible."
        )
    if finding.severity == "high":
        return (
            f"URGENT: {finding.label.capitalize()} near {finding.body_region} "
            "requires immediate attention."
        )
    if finding.severity == "medium":
        return (
            f"Monitor: {finding.label.capitalize()} near {finding.body_region} "
            "— maintain contact, reassess."
        )
    return (
        f"Note: {finding.label.capitalize()} near {finding.body_region} "
        "— low severity, continue observation."
    )


def _discover_scene_images(findings: list[Finding], reports_dir: Path) -> list[str]:
    """
    Discover all full-scene screenshots (full.jpg, full_1.jpg, ...) in evidence dirs.
    Returns report-relative paths when possible.
    """
    images: list[str] = []
    seen: set[str] = set()
    for f in findings or []:
        if not f.evidence or not f.evidence.full_image:
            continue
        full_rel = str(f.evidence.full_image)
        if full_rel not in seen:
            seen.add(full_rel)
            images.append(full_rel)
        # Try to discover sibling full_*.jpg in same evidence directory
        full_path = Path(full_rel)
        parent = full_path.parent
        if not parent:
            continue
        abs_parent = reports_dir / parent
        if abs_parent is None or not abs_parent.exists():
            continue
        for p in sorted(abs_parent.glob("full_*.jpg")):
            rel = str(Path(parent) / p.name)
            if rel not in seen:
                seen.add(rel)
                images.append(rel)
    return images


# ── ReportBuilder ────────────────────────────────────────────────────────

class ReportBuilder:
    """
    Build a final Markdown triage report from a TriageReport object.

    Usage::

        builder = ReportBuilder(output_dir="reports")
        path = builder.build_report(triage_report, meta={"session_id": "abc"})
        print(f"Report written to {path}")
    """

    def __init__(
        self,
        output_dir: str | Path = "reports",
        template_dir: str | Path | None = None,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._template_dir = Path(template_dir) if template_dir else (
            Path(__file__).parent / "templates"
        )
        self._env: Any = None

    def _get_env(self) -> Any:
        if self._env is not None:
            return self._env
        if not _JINJA_AVAILABLE:
            logger.warning("Jinja2 not installed — falling back to plain-text report.")
            return None
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        return self._env

    def build_report(
        self,
        report: TriageReport,
        meta: dict[str, Any] | None = None,
        scene_summary: str | None = None,
    ) -> str | None:
        """
        Render the triage report to Markdown and write to output_dir.

        Returns the path to the written file, or None on failure.
        """
        if scene_summary:
            report.scene_summary = scene_summary

        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        if not report.timestamp:
            report.timestamp = now_str

        # Speech-first triage: victim statement + answers drive priority; vision = support only
        self._fill_speech_first(report)

        md_content = self._render(report, meta or {}, now_str)
        if md_content is None:
            return None

        # Write
        self._output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"triage_{ts}.md"
        out_path = self._output_dir / filename
        try:
            out_path.write_text(md_content, encoding="utf-8")
            logger.info("ReportBuilder: wrote %s (%d chars)", out_path, len(md_content))
            # Auto-export to PDF when deps available
            try:
                from himpublic.utils.md_to_pdf import md_to_pdf
                pdf_path = md_to_pdf(out_path)
                if pdf_path:
                    logger.info("ReportBuilder: wrote PDF %s", pdf_path)
            except Exception as e:
                logger.debug("ReportBuilder: PDF export skipped: %s", e)
            return str(out_path)
        except OSError as e:
            logger.error("ReportBuilder: failed to write report: %s", e)
            return None

    def render_string(
        self,
        report: TriageReport,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Render report to a Markdown string (no file I/O)."""
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        if not report.timestamp:
            report.timestamp = now_str
        self._fill_speech_first(report)
        md = self._render(report, meta or {}, now_str)
        return md or ""

    def _fill_speech_first(self, report: TriageReport) -> None:
        """Compute speech-first priority and actions; fill report.chief_complaint, .triage_priority, .do_asap, etc."""
        try:
            from .triage_priority import compute_speech_first_triage
        except ImportError:
            return
        victim_statement = (report.victim_answers or {}).get("victim_statement", "")
        if not victim_statement and report.conversation_transcript:
            # Prefer victim lines from full transcript for richer speech-first triage context
            victim_lines = [
                line.split("Victim:", 1)[-1].strip()
                for line in report.conversation_transcript
                if "Victim:" in line
            ]
            if victim_lines:
                victim_statement = " ".join(victim_lines)
        if not victim_statement and report.scene_summary and "Victim reported:" in report.scene_summary:
            victim_statement = report.scene_summary.split("Victim reported:", 1)[-1].strip().rstrip("…")
        if not victim_statement and report.victim_answers:
            victim_statement = " ".join(str(v) for v in report.victim_answers.values() if v)
        sf = compute_speech_first_triage(
            victim_statement=victim_statement,
            victim_answers=report.victim_answers or {},
            vision_findings=report.findings,
            mechanism_context=report.mechanism_context or "",
        )
        report.chief_complaint = sf.chief_complaint
        report.triage_priority = sf.priority
        report.priority_rationale = sf.rationale
        report.mechanism_context = sf.mechanism_context
        report.suspected_injuries_ranked = [
            RankedSuspectedInjury(
                injury=si.injury,
                likelihood=si.likelihood,
                evidence_victim=si.evidence_victim,
                evidence_vision=si.evidence_vision,
                evidence_context=si.evidence_context,
            )
            for si in sf.suspected_injuries
        ]
        report.do_asap = list(sf.do_asap)
        report.for_responders = list(sf.for_responders)
        report.vision_findings_supporting = list(sf.vision_findings_supporting)

    # ── internal render ───────────────────────────────────────
    def _render(
        self,
        report: TriageReport,
        meta: dict[str, Any],
        now_str: str,
    ) -> str | None:
        # Fill screenshot gallery automatically unless caller already supplied custom list.
        if not report.scene_images:
            report.scene_images = _discover_scene_images(report.findings, self._output_dir)
        env = self._get_env()

        if env is not None:
            try:
                # Use speech-first template when we have priority (victim-driven)
                template_name = "triage_report_speech_first.md.j2" if report.triage_priority else "triage_report.md.j2"
                template = env.get_template(template_name)
                return template.render(report=report, meta=meta, now=now_str)
            except Exception as e:
                logger.error("Jinja2 rendering failed: %s — falling back", e)

        # ── Fallback: plain-text (no Jinja2) ──────────────────
        return self._render_fallback(report, meta, now_str)

    def _render_fallback(
        self,
        report: TriageReport,
        meta: dict[str, Any],
        now_str: str,
    ) -> str:
        """Basic Markdown without Jinja2. Uses speech-first structure when report.triage_priority is set."""
        if report.triage_priority:
            return self._render_fallback_speech_first(report, now_str)
        lines = [
            "# Triage Assessment Report",
            "",
            f"> **Generated:** {report.timestamp or now_str}",
            "",
            "---",
            "",
            "## Scene Summary",
            "",
            report.scene_summary or "_No scene summary available._",
            "",
            "---",
            "",
            "## Triage Findings",
            "",
        ]

        if report.findings:
            lines.append("| # | Finding | Body Region | Confidence | Severity |")
            lines.append("|---|---------|-------------|------------|----------|")
            for i, f in enumerate(report.findings, 1):
                sev = f"**{f.severity.upper()}**" if f.severity == "high" else f.severity
                lines.append(
                    f"| {i} | {f.label} | `{f.body_region}` | "
                    f"**{f.confidence:.2f}** ({f.confidence_label}) | {sev} |"
                )
            lines.append("")

            # Evidence gallery
            for i, f in enumerate(report.findings, 1):
                lines.append(f"### Finding {i}: {f.label}")
                if f.evidence:
                    lines.append(f"![annotated]({f.evidence.annotated_image})")
                    lines.append(f"![crop]({f.evidence.crop_image})")
                lines.append("")
        else:
            lines.append("_No findings detected._")
            lines.append("")

        if report.scene_images:
            lines.extend(["### Scene Screenshots (all views)", ""])
            for img in report.scene_images:
                lines.append(f"![scene]({img})")
            lines.append("")

        # Victim responses
        lines.extend([
            "---", "",
            "## Victim Responses", "",
        ])
        if report.victim_answers:
            lines.append("| Question | Response |")
            lines.append("|----------|----------|")
            for qid, ans in report.victim_answers.items():
                lines.append(f"| {qid} | {ans} |")
        else:
            lines.append("_No victim responses recorded._")
        lines.append("")

        if report.conversation_transcript:
            lines.extend(["## Conversation Transcript (full)", ""])
            for line in report.conversation_transcript:
                lines.append(f"- {line}")
            lines.append("")

        # Actions
        lines.extend(["---", "", "## Recommended Actions", ""])
        for f in report.findings:
            lines.append(f"- {finding_to_action(f)}")
        if not report.findings:
            lines.append("- Continue assessment.")
        lines.append("")

        # Narrative
        lines.extend(["---", "", "## Narrative Summary", ""])
        for f in report.findings:
            lines.append(finding_to_narrative(f, report.victim_answers))
        lines.append("")

        # Disclaimer
        lines.extend([
            "---", "",
            "> **Disclaimer**",
            ">",
            f"> {report.disclaimer}",
            "",
        ])

        return "\n".join(lines)

    def _render_fallback_speech_first(self, report: TriageReport, now_str: str) -> str:
        """Plain Markdown speech-first report when Jinja2 unavailable."""
        lines = [
            "# Triage Assessment Report",
            "",
            f"> **Generated:** {report.timestamp or now_str}",
            "",
            "---",
            "",
            "## 1) Chief Complaint (Victim's words)",
            "",
            report.chief_complaint or "_No victim statement._",
            "",
            "---",
            "",
            "## 2) Mechanism / Context",
            "",
            report.mechanism_context or "_No mechanism described._",
            "",
            "---",
            "",
            "## 3) Triage Priority (Speech-first)",
            "",
            f"**Priority:** {report.triage_priority.upper()}",
            "",
            f"**Rationale:** {report.priority_rationale}",
            "",
            "---",
            "",
            "## 4) Suspected Injuries (ranked differential)",
            "",
        ]
        if report.suspected_injuries_ranked:
            lines.append("| # | Suspected injury | Likelihood | Victim | Vision | Context |")
            lines.append("|---|------------------|------------|--------|--------|---------|")
            for i, si in enumerate(report.suspected_injuries_ranked, 1):
                lines.append(f"| {i} | {si.injury} | {si.likelihood} | {'✓' if si.evidence_victim else '—'} | {'✓' if si.evidence_vision else '—'} | {'✓' if si.evidence_context else '—'} |")
        else:
            lines.append("_No suspected injuries listed._")
        lines.extend(["", "---", "", "## 5) Do ASAP", ""])
        for step in report.do_asap or ["Call for responders; transmit location and summary."]:
            lines.append(f"- {step}")
        lines.extend(["", "---", "", "## 6) For Responders on Arrival", ""])
        for step in report.for_responders or ["Full primary survey; hemorrhage control if indicated; limb exam; immobilization as indicated."]:
            lines.append(f"- {step}")
        lines.extend(["", "---", "", "## 7) Visual Evidence (supporting only)", ""])
        for line in report.vision_findings_supporting or []:
            lines.append(f"- {line}")
        if report.scene_images:
            lines.extend(["", "### Scene Screenshots", ""])
            for img in report.scene_images:
                lines.append(f"![scene]({img})")
        if report.victim_answers:
            lines.extend(["", "## Victim Q&A", "", "| Key | Response |", "|-----|----------|"])
            for qid, ans in report.victim_answers.items():
                lines.append(f"| {qid} | {ans} |")
        if report.conversation_transcript:
            lines.extend(["", "## Conversation Transcript (full)", ""])
            for line in report.conversation_transcript:
                lines.append(f"- {line}")
        lines.extend(["", "---", "", "> **Disclaimer**", ">", f"> {report.disclaimer}", ""])
        return "\n".join(lines)
