"""Perception types - Detection, Observation, etc."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Detection:
    """Single object detection."""

    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    score: float
    cls_name: str


@dataclass
class Observation:
    """Perception summary for policy: one frame's state."""

    timestamp: float
    state: str  # mission state label, e.g. SEARCH, APPROACH
    persons: list[Detection]
    primary_person_center_offset: float  # cx_offset in [-1, 1], 0 = centered
    confidence: float  # 0..1 for primary person / scene
    obstacle_distance_m: float | None = None
    scene_caption: str | None = None
