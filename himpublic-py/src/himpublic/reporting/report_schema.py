"""Report schema validation (dataclasses + manual validate(), no pydantic)."""

from __future__ import annotations

from .types import (
    IncidentReport,
    LocationInfo,
    VictimSummary,
    HazardsDebris,
    InjuryFinding,
    MedicalChatbotSection,
    ImageEvidence,
    RecommendedActionPackage,
    CommsStatus,
    TriageDecision,
)


def _check_type(value: object, expected: type, path: str) -> list[str]:
    errs: list[str] = []
    if value is None and expected != type(None):
        if getattr(expected, "__origin__", None) is type(None) or str(expected).startswith("None"):
            return errs
        try:
            from typing import get_origin, get_args
            if get_origin(expected) is type(None):
                return errs
        except Exception:
            pass
    if value is not None and not isinstance(value, expected):
        errs.append(f"{path}: expected {expected.__name__}, got {type(value).__name__}")
    return errs


def _validate_location(loc: LocationInfo, path: str) -> list[str]:
    errs: list[str] = []
    valid_status = ("clear", "partially_blocked", "blocked", "unknown")
    if loc.approach_path_status not in valid_status:
        errs.append(f"{path}.approach_path_status must be one of {valid_status}")
    return errs


def _validate_injury(i: InjuryFinding, path: str) -> list[str]:
    errs: list[str] = []
    valid_type = ("bleeding", "burn", "fracture", "laceration", "unknown")
    if i.type not in valid_type:
        errs.append(f"{path}.type must be one of {valid_type}")
    valid_sev = ("minor", "moderate", "severe", "unknown")
    if i.severity not in valid_sev:
        errs.append(f"{path}.severity must be one of {valid_sev}")
    return errs


def _validate_medical(m: MedicalChatbotSection, path: str) -> list[str]:
    errs: list[str] = []
    valid_priority = ("RED", "YELLOW", "GREEN", "BLACK", "UNKNOWN")
    if m.triage_priority not in valid_priority:
        errs.append(f"{path}.triage_priority must be one of {valid_priority}")
    return errs


def validate_report(report: IncidentReport) -> list[str]:
    """Validate IncidentReport. Returns list of error strings; empty if valid."""
    errs: list[str] = []
    if not report.incident_id:
        errs.append("incident_id is required")
    if not isinstance(report.timestamp_start, (int, float)):
        errs.append("timestamp_start must be number")
    if not isinstance(report.timestamp_end, (int, float)):
        errs.append("timestamp_end must be number")
    if not report.robot_id:
        errs.append("robot_id is required")
    if report.location is not None:
        errs.extend(_validate_location(report.location, "location"))
    for i, inj in enumerate(report.injuries):
        errs.extend(_validate_injury(inj, f"injuries[{i}]"))
    if report.medical_chatbot is not None:
        errs.extend(_validate_medical(report.medical_chatbot, "medical_chatbot"))
    return errs
