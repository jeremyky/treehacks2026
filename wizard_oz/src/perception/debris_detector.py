"""
Debris detector: detect_debris(frame) -> list[DebrisFinding].
Placeholder: returns empty list unless key 'd' was pressed (toggle_debris).
Swappable with real model later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import DebrisFinding

if TYPE_CHECKING:
    import numpy as np

_toggle_debris_detected: bool = False


def set_debris_toggle(value: bool) -> None:
    global _toggle_debris_detected
    _toggle_debris_detected = value


def get_debris_toggle() -> bool:
    return _toggle_debris_detected


def detect_debris(frame: "np.ndarray") -> list[DebrisFinding]:
    """
    Detect debris/rubble in frame. Returns list of DebrisFinding.
    Placeholder: if user pressed 'd', return one fake finding.
    """
    if _toggle_debris_detected:
        return [
            DebrisFinding(
                confidence=0.85,
                bbox_xyxy=(150.0, 200.0, 350.0, 350.0),
                movable=True,
                description="rubble near target",
                extra={"source": "wizard_of_oz_key"},
            )
        ]
    return []
