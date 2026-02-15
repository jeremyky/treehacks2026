"""Rubble detection — now powered by YOLO-World open-vocabulary detection.

See openvocab.py for the real implementation.
This file exists for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from himpublic.perception.openvocab import OpenVocabDetector, RubbleDetection, NO_DETECTION


def detect_rubble(frame: Any) -> bool:
    """Legacy compat: return True if rubble detected in a numpy frame."""
    import numpy as np
    if not isinstance(frame, np.ndarray):
        return False
    detector = OpenVocabDetector()
    result = detector.detect(frame)
    return result.found
