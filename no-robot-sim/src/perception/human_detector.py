"""
Human detector: detect_humans(frame) -> list[Detection].
Placeholder: returns empty list unless key 'h' was pressed (toggle_human).
Swappable with real model later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import Detection

if TYPE_CHECKING:
    import numpy as np

# Module-level toggle set by main loop when user presses 'h'
_toggle_human_detected: bool = False


def set_human_toggle(value: bool) -> None:
    global _toggle_human_detected
    _toggle_human_detected = value


def get_human_toggle() -> bool:
    return _toggle_human_detected


def detect_humans(frame: "np.ndarray") -> list[Detection]:
    """
    Detect humans in frame. Returns list of Detection.
    Placeholder: if user pressed 'h', return one fake detection (confidence 0.9, fake bearing).
    """
    if _toggle_human_detected:
        return [
            Detection(
                confidence=0.9,
                bearing_rad=0.0,
                distance_m=2.0,
                bbox_xyxy=(100.0, 100.0, 300.0, 400.0),
                extra={"source": "wizard_of_oz_key"},
            )
        ]
    return []
