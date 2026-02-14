"""Canonical report types: dataclasses for triage, location, hazards, evidence, QA, images."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Pose:
    x: float
    y: float
    yaw: float


@dataclass
class Detection:
    confidence: float
    method: list[str]  # ["vision", "audio", "manual"]
    bbox: tuple[float, float, float, float] | None = None  # x1,y1,x2,y2


@dataclass
class LocationInfo:
    frame: str  # "local"
    x: float
    y: float
    yaw: float
    floor: str | None = None
    area_label: str | None = None
    confidence: float = 0.0
    approach_path_status: str = "unknown"  # "clear"|"partially_blocked"|"blocked"
    nav_notes: str = ""


@dataclass
class VictimSummary:
    victim_id: str
    detection: Detection
    responsiveness: dict[str, Any]  # conscious: bool|unknown, responds_to_voice: bool|unknown
    breathing: str = "unknown"  # "normal"|"labored"|"unknown"
    mobility: str = "unknown"  # "can_move"|"limited"|"unknown"


@dataclass
class Hazard:
    type: str
    severity: str
    confidence: float
    notes: str = ""


@dataclass
class DebrisFinding:
    type: str
    movable: bool
    confidence: float
    pose: tuple[float, float] | None = None  # x, y
    notes: str = ""


@dataclass
class HazardsDebris:
    hazards: list[Hazard] = field(default_factory=list)
    debris: list[DebrisFinding] = field(default_factory=list)
    recommended_tools: list[str] = field(default_factory=list)


@dataclass
class InjuryFinding:
    type: str  # "bleeding"|"burn"|"fracture"|"laceration"|"unknown"
    body_region: str
    severity: str  # "minor"|"moderate"|"severe"|"unknown"
    confidence: float
    evidence_image_ids: list[str] = field(default_factory=list)


@dataclass
class QAItem:
    question: str
    timestamp: float


@dataclass
class QAAnswer:
    answer: str
    timestamp: float


@dataclass
class TriageRationaleItem:
    claim: str
    evidence: str  # references observed findings or answers


@dataclass
class TriageDecision:
    triage_priority: str  # "RED"|"YELLOW"|"GREEN"|"BLACK"|"UNKNOWN"
    triage_rationale: list[TriageRationaleItem] = field(default_factory=list)
    overall_confidence: float = 0.0


@dataclass
class MedicalChatbotSection:
    questions_asked: list[QAItem] = field(default_factory=list)
    answers: list[QAAnswer] = field(default_factory=list)
    chatbot_summary: str = ""
    triage_priority: str = "UNKNOWN"
    triage_rationale: list[TriageRationaleItem] = field(default_factory=list)
    overall_confidence: float = 0.0


@dataclass
class ImageEvidence:
    image_id: str
    kind: str  # "rgb"|"annotated"|"injury_crop"|"depth"
    path: str
    timestamp: float
    description: str = ""


@dataclass
class RecommendedAction:
    action: str
    priority: str
    why: str


@dataclass
class RecommendedActionPackage:
    recommended_actions: list[RecommendedAction] = field(default_factory=list)


@dataclass
class CommsStatus:
    sent: bool
    endpoint: str = ""
    error: str | None = None


@dataclass
class IncidentReport:
    incident_id: str
    timestamp_start: float
    timestamp_end: float
    robot_id: str
    operator: str | None = None
    location: LocationInfo | None = None
    victim: VictimSummary | None = None
    hazards_debris: HazardsDebris | None = None
    injuries: list[InjuryFinding] = field(default_factory=list)
    medical_chatbot: MedicalChatbotSection | None = None
    images: list[ImageEvidence] = field(default_factory=list)
    recommended_actions: RecommendedActionPackage | None = None
    comms_status: CommsStatus | None = None
