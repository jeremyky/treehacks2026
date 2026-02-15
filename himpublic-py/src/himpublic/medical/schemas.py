"""
Triage CV schemas — single source of truth for the medical assessment pipeline.

These dataclasses are used across:
  - MedicalAssessor (produces Findings)
  - EvidenceCollector (fills EvidencePaths)
  - QuestionPlanner (reads Findings)
  - ReportBuilder (reads TriageReport)

NOTE: These are *separate* from ``medical.report_schema`` which defines the
      rich command-center incident report.  The two can be bridged (Finding →
      SuspectedInjury) when building the final report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Finding — one suspected injury cue detected in a frame
# ---------------------------------------------------------------------------

FindingType = Literal[
    "suspected_bleeding",
    "suspected_burn",
    "suspected_bruise",
    "suspected_wound",
    "suspected_immobility",
    "unknown",
]

SeverityLevel = Literal["low", "medium", "high"]


@dataclass
class EvidencePaths:
    """Relative paths to saved evidence images for one finding."""
    full_image: str = ""
    crop_image: str = ""
    annotated_image: str = ""


@dataclass
class Finding:
    """A single suspected injury cue detected by computer vision."""

    finding_type: FindingType = "unknown"
    label: str = ""                         # e.g. "possible bleeding"
    confidence: float = 0.0                 # 0..1
    severity: SeverityLevel = "low"
    body_region: str = "unknown"            # e.g. "left_lower_leg"
    bbox_xyxy: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    prompt: str = ""                        # text prompt that triggered detector
    signals: dict[str, Any] = field(default_factory=dict)
    evidence: EvidencePaths | None = None

    # Convenience ---------------------------------------------------------

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.70:
            return "very likely"
        if self.confidence >= 0.45:
            return "likely"
        return "possible"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "finding_type": self.finding_type,
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "severity": self.severity,
            "body_region": self.body_region,
            "bbox_xyxy": self.bbox_xyxy,
            "prompt": self.prompt,
            "signals": self.signals,
        }
        if self.evidence:
            d["evidence"] = {
                "full_image": self.evidence.full_image,
                "crop_image": self.evidence.crop_image,
                "annotated_image": self.evidence.annotated_image,
            }
        return d


# ---------------------------------------------------------------------------
# TriageReport — aggregated output for the report builder
# ---------------------------------------------------------------------------

@dataclass
class RankedSuspectedInjury:
    """One item in ranked differential with evidence source tags (Victim/Vision/Context)."""
    injury: str = ""
    likelihood: str = ""  # likely | possible | low
    evidence_victim: bool = False
    evidence_vision: bool = False
    evidence_context: bool = False


@dataclass
class TriageReport:
    """Aggregated triage data for report generation."""

    timestamp: str = ""
    scene_summary: str = ""
    victim_answers: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Full dialogue transcript (robot + victim), in chronological lines.
    conversation_transcript: list[str] = field(default_factory=list)
    # All scene screenshots to embed (e.g., evidence/.../full.jpg, full_1.jpg, ...).
    scene_images: list[str] = field(default_factory=list)
    disclaimer: str = (
        "This is triage support and documentation only; "
        "not a medical diagnosis. All findings are suspected "
        "and must be confirmed by a qualified medical responder."
    )

    # Speech-first triage (optional; when set, report uses priority + Do ASAP / For Responders)
    chief_complaint: str = ""
    triage_priority: str = ""           # Immediate | Urgent | Delayed | Minor | Expectant
    priority_rationale: str = ""
    mechanism_context: str = ""
    suspected_injuries_ranked: list[RankedSuspectedInjury] = field(default_factory=list)
    do_asap: list[str] = field(default_factory=list)
    for_responders: list[str] = field(default_factory=list)
    vision_findings_supporting: list[str] = field(default_factory=list)  # supporting only, no severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "scene_summary": self.scene_summary,
            "victim_answers": self.victim_answers,
            "findings": [f.to_dict() for f in self.findings],
            "notes": self.notes,
            "disclaimer": self.disclaimer,
        }
