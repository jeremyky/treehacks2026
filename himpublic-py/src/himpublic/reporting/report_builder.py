"""Report builder: merge observations, QA + triage, and images into one IncidentReport."""

from __future__ import annotations

import time
import uuid

from .types import (
    IncidentReport,
    LocationInfo,
    VictimSummary,
    HazardsDebris,
    InjuryFinding,
    MedicalChatbotSection,
    ImageEvidence,
    RecommendedActionPackage,
    RecommendedAction,
    CommsStatus,
)


def build_report(
    *,
    incident_id: str | None = None,
    timestamp_start: float | None = None,
    timestamp_end: float | None = None,
    robot_id: str = "robot-1",
    operator: str | None = None,
    location: LocationInfo | None = None,
    victim: VictimSummary | None = None,
    hazards_debris: HazardsDebris | None = None,
    injuries: list[InjuryFinding] | None = None,
    medical_chatbot: MedicalChatbotSection | None = None,
    images: list[ImageEvidence] | None = None,
    recommended_actions: RecommendedActionPackage | list[RecommendedAction] | None = None,
    comms_status: CommsStatus | None = None,
) -> IncidentReport:
    """Merge all sections into a single IncidentReport. Fills identity if not provided."""
    now = time.time()
    incident_id = incident_id or str(uuid.uuid4())
    ts_start = timestamp_start if timestamp_start is not None else now
    ts_end = timestamp_end if timestamp_end is not None else now
    injuries = injuries or []
    images = images or []
    if recommended_actions is not None and not isinstance(recommended_actions, RecommendedActionPackage):
        recommended_actions = RecommendedActionPackage(recommended_actions=recommended_actions)
    return IncidentReport(
        incident_id=incident_id,
        timestamp_start=ts_start,
        timestamp_end=ts_end,
        robot_id=robot_id,
        operator=operator,
        location=location,
        victim=victim,
        hazards_debris=hazards_debris,
        injuries=injuries,
        medical_chatbot=medical_chatbot,
        images=images,
        recommended_actions=recommended_actions,
        comms_status=comms_status,
    )
