"""Perception: human, debris, injury detectors. Swappable implementations."""

from .types import Detection, DebrisFinding, InjuryFinding
from .human_detector import detect_humans
from .debris_detector import detect_debris
from .injury_detector import detect_injuries

__all__ = [
    "Detection",
    "DebrisFinding",
    "InjuryFinding",
    "detect_humans",
    "detect_debris",
    "detect_injuries",
]
