"""YOLO-based person detection + observation summary."""

from __future__ import annotations

import logging
import time
from typing import Any

import cv2
import numpy as np

from .types import Detection, Observation

logger = logging.getLogger(__name__)

PERSON_CLS_ID = 0  # COCO class id for person


def _load_model(model_path: str = "yolov8n.pt") -> Any:
    """Load YOLO model. Lazily imported."""
    from ultralytics import YOLO
    return YOLO(model_path)


def _bbox_center_x(bbox: tuple[float, float, float, float]) -> float:
    """Center x of bbox (x1, y1, x2, y2)."""
    return (bbox[0] + bbox[2]) / 2.0


def primary_person_center_offset(
    frame_width: int,
    persons: list[Detection],
) -> float:
    """
    Normalized offset of primary (largest) person center from image center.
    Returns in [-1, 1]: negative = person left of center, positive = right, 0 = centered.
    If no persons, return 0.0.
    """
    if not persons or frame_width <= 0:
        return 0.0
    # Primary = largest bbox area
    primary = max(persons, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
    cx = _bbox_center_x(primary.bbox)
    image_center = frame_width / 2.0
    half = frame_width / 2.0
    if half <= 0:
        return 0.0
    offset = (cx - image_center) / half
    return max(-1.0, min(1.0, offset))


class PersonDetector:
    """YOLO person detector with configurable model and threshold."""

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        threshold: float = 0.5,
    ) -> None:
        self._model_path = model_path
        self._threshold = threshold
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            self._model = _load_model(self._model_path)
            logger.info("PersonDetector: loaded model %s", self._model_path)
        return self._model

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """
        Detect persons in BGR frame. Returns list of Detection.
        Filter to class person only.
        """
        model = self._get_model()
        results = model(frame, verbose=False)
        detections: list[Detection] = []
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                if cls_id != PERSON_CLS_ID:
                    continue
                conf = float(box.conf[0])
                if conf < self._threshold:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(
                    bbox=(float(x1), float(y1), float(x2), float(y2)),
                    score=conf,
                    cls_name="person",
                ))
        return detections

    def observe(
        self,
        frame: np.ndarray,
        state: str = "SEARCH",
    ) -> Observation:
        """Run detection and build Observation summary (timestamp, persons, primary offset, confidence)."""
        detections = self.detect(frame)
        h, w = frame.shape[:2]
        offset = primary_person_center_offset(w, detections)
        confidence = float(detections[0].score) if detections else 0.0
        return Observation(
            timestamp=time.monotonic(),
            state=state,
            persons=detections,
            primary_person_center_offset=offset,
            confidence=confidence,
            obstacle_distance_m=None,
            scene_caption=None,
        )


def detect_person(frame: dict[str, Any] | np.ndarray) -> bool:
    """
    Legacy compatibility: return True if person detected.
    frame: either dict (MockRobot style with person_detected) or np.ndarray (BGR image).
    """
    if isinstance(frame, dict):
        return bool(frame.get("person_detected", False))
    return False


def draw_boxes(frame: np.ndarray, detections: list[Detection], color: tuple = (0, 255, 0), thickness: int = 2) -> np.ndarray:
    """Draw detection boxes on frame. Returns copy with boxes drawn."""
    out = frame.copy()
    for d in detections:
        x1, y1, x2, y2 = [int(v) for v in d.bbox]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
        label = f"{d.cls_name} {d.score:.2f}"
        cv2.putText(out, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return out
