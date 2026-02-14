"""Command center report pipeline: schema, artifact store, report/document builders."""

from .types import (
    Pose,
    Detection,
    InjuryFinding,
    DebrisFinding,
    Hazard,
    ImageEvidence,
    QAItem,
    TriageDecision,
    LocationInfo,
    VictimSummary,
    HazardsDebris,
    MedicalChatbotSection,
    RecommendedActionPackage,
    CommsStatus,
    IncidentReport,
)
from .report_schema import validate_report
from .artifact_store import ArtifactStore, save_report_json, report_to_dict, image_id_from_bytes
from .report_builder import build_report
from .document_builder import build_markdown
from .render_medical_report import (
    generate_medical_report,
    render_medical_report_md,
    build_medical_report_from_observations,
    assign_image_captions_and_evidence,
)

__all__ = [
    "Pose",
    "Detection",
    "InjuryFinding",
    "DebrisFinding",
    "Hazard",
    "ImageEvidence",
    "QAItem",
    "TriageDecision",
    "LocationInfo",
    "VictimSummary",
    "HazardsDebris",
    "MedicalChatbotSection",
    "RecommendedActionPackage",
    "CommsStatus",
    "IncidentReport",
    "validate_report",
    "ArtifactStore",
    "save_report_json",
    "report_to_dict",
    "image_id_from_bytes",
    "build_report",
    "build_markdown",
    "generate_medical_report",
    "render_medical_report_md",
    "build_medical_report_from_observations",
    "assign_image_captions_and_evidence",
]
