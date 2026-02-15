"""Medical / SAR report schema and types for command-center incident reports.

Also provides the triage CV pipeline:
  - schemas (Finding, EvidencePaths, TriageReport)
  - MedicalAssessor (pose + open-vocab + redness heuristic)
  - EvidenceCollector (burst capture, sharpest frame, annotation)
  - QuestionPlanner (finding → targeted questions)
  - ReportBuilder (Jinja2 Markdown report)
  - TriagePipeline (coordinator)
"""

from .report_schema import (
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

# Triage CV pipeline (lazy imports — these may pull in cv2 / mediapipe)
from .schemas import Finding, EvidencePaths, TriageReport

__all__ = [
    # Command-center report schema (existing)
    "IncidentMeta",
    "LocationAccess",
    "PatientSummary",
    "ABCDEFinding",
    "ABCDEChecklist",
    "SuspectedInjury",
    "HazardNearby",
    "MediaEvidence",
    "MediaImage",
    "MediaAudio",
    "EvidenceItem",
    "UncertaintyItem",
    "RecommendedNextAction",
    "MedicalReport",
    "ReportConfig",
    # Triage CV schemas (new)
    "Finding",
    "EvidencePaths",
    "TriageReport",
]
