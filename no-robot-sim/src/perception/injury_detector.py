"""
Injury detector: detect_injuries(frame) -> list[InjuryFinding].
Placeholder: returns empty list unless key 'i' was pressed (toggle_injury).
Swappable with real model later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import InjuryFinding

if TYPE_CHECKING:
    import numpy as np

_toggle_injury_detected: bool = False


def set_injury_toggle(value: bool) -> None:
    global _toggle_injury_detected
    _toggle_injury_detected = value


def get_injury_toggle() -> bool:
    return _toggle_injury_detected


def detect_injuries(frame: "np.ndarray") -> list[InjuryFinding]:
    """
    Detect injuries in frame. Returns list of InjuryFinding.
    Placeholder: if user pressed 'i', return a couple fake findings.
    """
    if _toggle_injury_detected:
        return [
            InjuryFinding(
                label="bleeding",
                body_region="arm",
                severity_estimate="low",
                confidence=0.8,
                extra={"source": "wizard_of_oz_key"},
            ),
            InjuryFinding(
                label="possible_fracture_indicator",
                body_region="leg",
                severity_estimate="medium",
                confidence=0.6,
                extra={"source": "wizard_of_oz_key"},
            ),
        ]
    return []
