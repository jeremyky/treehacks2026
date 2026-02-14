"""Perception types: Detection, DebrisFinding, InjuryFinding. Swappable detector signatures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Detection:
    """Human detection. Bearing/yaw relative to camera; pose optional."""

    confidence: float
    bearing_rad: float | None = None  # angle to target
    distance_m: float | None = None
    bbox_xyxy: tuple[float, float, float, float] | None = None
    extra: dict[str, Any] | None = None


@dataclass
class DebrisFinding:
    """Debris / rubble finding."""

    confidence: float
    bbox_xyxy: tuple[float, float, float, float] | None = None
    movable: bool = True
    description: str = ""
    extra: dict[str, Any] | None = None


@dataclass
class InjuryFinding:
    """Injury finding for report."""

    label: str  # e.g. "bleeding", "burn", "fracture_indicator"
    body_region: str = ""
    severity_estimate: str = ""  # e.g. "low", "medium", "high"
    confidence: float = 0.0
    extra: dict[str, Any] | None = None
