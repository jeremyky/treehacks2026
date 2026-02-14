"""
Schema for Medical / SAR incident report (Open Evidence style).
Schema-driven; prompt-agnostic. Missing sections are allowed (omit or empty).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- A) Header / Incident Meta ---


@dataclass
class IncidentMeta:
    report_id: str
    session_id: str
    timestamp_start: float
    timestamp_end: float
    timezone: str = "UTC"
    robot_id: str = ""
    operator_id: str = ""
    environment_label: str = ""  # building/floor/room if known


# --- B) Location & Access ---


@dataclass
class LocationAccess:
    location_estimate: str = ""
    coordinates: str = ""  # e.g. "x=1.2, y=2.3" or "lat,lon" if available
    location_derivation: str = ""  # visual landmarks, operator note, waypoint, audio direction
    access_constraints: list[str] = field(default_factory=list)  # blocked doors, stairs, rubble
    suggested_approach_route: str = ""
    evidence_ids: list[str] = field(default_factory=list)


# --- C) Patient Summary ---


@dataclass
class PatientSummary:
    one_liner: str = ""  # 1–2 lines
    estimated_age_range: str = ""  # optional, mark as estimated
    estimated_sex: str = ""  # optional, mark as estimated
    consciousness: str = ""  # responsive to voice / pain / none
    primary_concern: str = ""
    triage_category: str = ""  # Immediate / Delayed / Minimal / Expectant (START/JumpSTART-ish)
    overall_confidence: float = 0.0
    confidence_explanation: str = ""
    evidence_ids: list[str] = field(default_factory=list)


# --- D) Findings: ABCDE + Suspected Injuries + Hazards ---


@dataclass
class ABCDEFinding:
    status: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""


@dataclass
class ABCDEChecklist:
    airway: ABCDEFinding = field(default_factory=ABCDEFinding)
    breathing: ABCDEFinding = field(default_factory=ABCDEFinding)
    circulation: ABCDEFinding = field(default_factory=ABCDEFinding)
    disability: ABCDEFinding = field(default_factory=ABCDEFinding)
    exposure: ABCDEFinding = field(default_factory=ABCDEFinding)


@dataclass
class SuspectedInjury:
    injury_type: str = ""  # laceration, burn, fracture suspected, crush injury suspected, etc.
    body_location: str = ""
    severity_estimate: str = ""  # mild / moderate / severe
    confidence: float = 0.0
    rationale: str = ""
    immediate_actions_recommended: list[str] = field(default_factory=list)  # suggestions, not orders
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class HazardNearby:
    description: str = ""  # fire/smoke, unstable debris, downed wires, gas smell, water, etc.
    risk_level: str = ""
    evidence_ids: list[str] = field(default_factory=list)


# --- E) Media Evidence ---


@dataclass
class MediaImage:
    file_path: str = ""  # relative
    timestamp: float = 0.0
    caption: str = ""
    evidence_id: str = ""
    section: str = "scene"  # "scene_overview" | "injury_closeup" | "other"


@dataclass
class MediaAudio:
    file_path: str = ""
    transcript_snippet: str = ""
    timestamp: float = 0.0
    evidence_id: str = ""
    confidence: float = 0.0


@dataclass
class MediaEvidence:
    scene_overview_images: list[MediaImage] = field(default_factory=list)
    injury_closeup_images: list[MediaImage] = field(default_factory=list)
    audio: list[MediaAudio] = field(default_factory=list)


# --- F) Evidence & Provenance (Open Evidence style) ---


@dataclass
class EvidenceItem:
    evidence_id: str
    type: str  # image | audio | text | model_output | operator_note
    timestamp: float
    source: str  # camera, mic, operator, model name
    file_path: str = ""
    confidence: float = 0.0
    summary: str = ""
    model_metadata: dict[str, Any] = field(default_factory=dict)


# --- G) Uncertainty / Assumptions ---


@dataclass
class UncertaintyItem:
    item: str
    reason: str
    alternative_hypotheses: list[str] = field(default_factory=list)


# --- H) Recommended Next Actions ---


@dataclass
class RecommendedNextAction:
    action: str
    urgency: str = ""  # e.g. "high", "medium", "low"
    safety_warning: bool = False


# --- I) Disclaimer (stored as flag; text is fixed in renderer) ---
# No dataclass needed; renderer always appends disclaimer.


# --- Root Report ---


@dataclass
class MedicalReport:
    meta: IncidentMeta
    location_access: LocationAccess | None = None
    patient_summary: PatientSummary | None = None
    abcde: ABCDEChecklist | None = None
    suspected_injuries: list[SuspectedInjury] = field(default_factory=list)
    hazards_nearby: list[HazardNearby] = field(default_factory=list)
    media: MediaEvidence | None = None
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    uncertainties: list[UncertaintyItem] = field(default_factory=list)
    recommended_actions: list[RecommendedNextAction] = field(default_factory=list)
    # Disclaimer is always rendered; no field needed.


# --- Config for renderer ---


@dataclass
class ReportConfig:
    include_pdf: bool = False
    include_raw_transcripts: bool = False
    max_images_per_section: int = 10
    confidence_likely_threshold: float = 0.7
    confidence_possible_threshold: float = 0.4
    # Wording: >= likely -> "likely", >= possible -> "possible", else "uncertain"
