"""Mission state machine - states and transitions. Use Phase for high-level phases."""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
from typing import Any

from .phases import Phase

__all__ = ["MissionState", "MissionEvent", "AssessmentReport", "Phase"]


class MissionState(Enum):
    """Legacy mission states (map from Phase for backward compat)."""

    SEARCH = "search"       # Rotate/scan, call out, listen
    APPROACH = "approach"   # Move toward detected person
    ASSESS = "assess"       # Run injury detection, produce report
    REPORT = "report"       # Send report to command center
    DONE = "done"           # Mission complete


class MissionEvent(Enum):
    """Events that drive state transitions."""

    PERSON_DETECTED = "person_detected"
    REACHED_TARGET = "reached_target"
    ASSESSMENT_COMPLETE = "assessment_complete"
    REPORT_SENT = "report_sent"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class AssessmentReport:
    """Structured report from ASSESS state."""

    person_detected: bool
    injury_detected: bool
    rubble_detected: bool
    summary: str
    raw_data: dict[str, Any] | None = None
