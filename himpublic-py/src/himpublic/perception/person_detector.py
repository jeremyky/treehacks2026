"""Object detection for the HIM Public pipeline.

Detection targets:
  - "person": YOLO COCO class 0 only.
  - "rubble": layered detection with three backends (tried in order):
      1. **YOLO-World open-vocab** (primary) — detects "cardboard box", "package",
         "debris", etc. via text prompts. No training needed.
      2. **QR code** (secondary) — if a QR fiducial is on the rubble, instant detection.
      3. **YOLO COCO fallback** — any non-person COCO class (suitcase, backpack, etc.).

Why not just YOLO COCO?
  COCO-80 has no "cardboard box", "rubble", or "debris" class. A plain Amazon box
  will not be detected. YOLO-World solves this with open-vocabulary prompts.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import cv2
import numpy as np

from .types import Detection, Observation

logger = logging.getLogger(__name__)

PERSON_CLS_ID = 0  # COCO class id for person

# COCO class names (subset) — used to label rubble detections
COCO_NAMES: dict[int, str] = {
    0: "person", 24: "backpack", 25: "umbrella", 26: "handbag", 28: "suitcase",
    39: "bottle", 41: "cup", 56: "chair", 57: "couch", 58: "potted_plant",
    60: "dining_table", 62: "tv", 63: "laptop", 64: "mouse", 66: "keyboard",
    67: "cell_phone", 73: "book", 74: "clock", 76: "scissors",
}

# QR code detector (OpenCV built-in, no ML needed)
_qr_detector: cv2.QRCodeDetector | None = None


def _get_qr_detector() -> cv2.QRCodeDetector:
    global _qr_detector
    if _qr_detector is None:
        _qr_detector = cv2.QRCodeDetector()
    return _qr_detector


def detect_qr_rubble(frame: np.ndarray) -> list[Detection]:
    """Detect QR codes in the frame. Each QR code = one rubble detection.

    Returns Detection with cls_name = "rubble:<qr_text>" and the bounding box
    of the QR code polygon.
    """
    detector = _get_qr_detector()
    detections: list[Detection] = []
    try:
        # detectAndDecodeMulti finds all QR codes in one shot
        ok, decoded_texts, points, _ = detector.detectAndDecodeMulti(frame)
        if ok and decoded_texts is not None:
            for i, text in enumerate(decoded_texts):
                text = (text or "").strip()
                if not text:
                    continue
                # Get bounding box from QR polygon points
                if points is not None and i < len(points):
                    pts = points[i]
                    x_coords = pts[:, 0]
                    y_coords = pts[:, 1]
                    x1, y1 = float(x_coords.min()), float(y_coords.min())
                    x2, y2 = float(x_coords.max()), float(y_coords.max())
                else:
                    # Fallback: center of frame
                    h, w = frame.shape[:2]
                    x1, y1, x2, y2 = w * 0.25, h * 0.25, w * 0.75, h * 0.75

                detections.append(Detection(
                    bbox=(x1, y1, x2, y2),
                    score=1.0,  # QR detection is binary — if decoded, confidence = 1.0
                    cls_name=f"rubble ({text[:30]})",
                ))
                logger.info("QR rubble detected: %r at (%.0f,%.0f)-(%.0f,%.0f)", text, x1, y1, x2, y2)
    except Exception as e:
        # detectAndDecodeMulti can fail on some frames — just skip
        logger.debug("QR detection error (non-fatal): %s", e)
    return detections


def _load_model(model_path: str = "yolov8n.pt") -> Any:
    """Load YOLO model. Lazily imported."""
    from ultralytics import YOLO
    return YOLO(model_path)


def _bbox_center_x(bbox: tuple[float, float, float, float]) -> float:
    """Center x of bbox (x1, y1, x2, y2)."""
    return (bbox[0] + bbox[2]) / 2.0


def primary_detection_center_offset(
    frame_width: int,
    detections: list[Detection],
) -> float:
    """
    Normalized offset of primary (largest) detection center from image center.
    Returns in [-1, 1]: negative = left of center, positive = right, 0 = centered.
    If no detections, return 0.0.
    """
    if not detections or frame_width <= 0:
        return 0.0
    primary = max(detections, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
    cx = _bbox_center_x(primary.bbox)
    image_center = frame_width / 2.0
    half = frame_width / 2.0
    if half <= 0:
        return 0.0
    offset = (cx - image_center) / half
    return max(-1.0, min(1.0, offset))


# Backward compat alias
primary_person_center_offset = primary_detection_center_offset


class PersonDetector:
    """Multi-backend detector with configurable target.

    target="person" → YOLO COCO class 0 only.
    target="rubble" → layered: YOLO-World open-vocab → QR code → YOLO COCO fallback.
    """

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        threshold: float = 0.5,
        target: str = "person",
        rubble_prompts: list[str] | None = None,
    ) -> None:
        self._model_path = model_path
        self._threshold = threshold
        self._target = target  # "person" or "rubble"
        self._model: Any = None  # YOLO COCO model (lazy)
        self._openvocab: Any = None  # OpenVocabDetector (lazy, rubble only)
        self._openvocab_init = False
        self._rubble_prompts = rubble_prompts

    def _get_model(self) -> Any:
        """Load YOLO COCO model (for person mode or rubble fallback)."""
        if self._model is None:
            self._model = _load_model(self._model_path)
            logger.info("PersonDetector: loaded COCO model %s (target=%s)", self._model_path, self._target)
        return self._model

    def _get_openvocab(self):
        """Lazy-init OpenVocabDetector for rubble mode. Returns None if unavailable."""
        if self._openvocab_init:
            return self._openvocab
        self._openvocab_init = True
        try:
            from himpublic.perception.openvocab import OpenVocabDetector
            kwargs = {}
            if self._rubble_prompts:
                kwargs["prompts"] = self._rubble_prompts
            self._openvocab = OpenVocabDetector(**kwargs)
            logger.info("OpenVocabDetector initialized for rubble detection")
        except Exception as e:
            logger.warning("OpenVocabDetector unavailable (%s) — using QR + COCO fallback", e)
            self._openvocab = None
        return self._openvocab

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Detect objects in BGR frame. Returns list of Detection.

        Person mode: YOLO COCO class 0 only.
        Rubble mode (layered, first hit wins):
          1. YOLO-World open-vocab (text-prompted: "cardboard box", "debris", etc.)
          2. QR code fiducial detection
          3. YOLO COCO fallback (any non-person class)
        """
        if self._target == "rubble":
            return self._detect_rubble(frame)
        return self._detect_person(frame)

    def _detect_person(self, frame: np.ndarray) -> list[Detection]:
        """YOLO COCO person-only detection."""
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

    def _detect_rubble(self, frame: np.ndarray) -> list[Detection]:
        """Layered rubble detection: open-vocab → QR → COCO fallback."""

        # ── Layer 1: YOLO-World open-vocab (primary) ──
        ov = self._get_openvocab()
        if ov is not None:
            result = ov.detect(frame)
            if result.found:
                return [Detection(
                    bbox=result.bbox_xyxy,
                    score=result.score,
                    cls_name=result.label,
                )]

        # ── Layer 2: QR code fiducial (secondary) ──
        qr_detections = detect_qr_rubble(frame)
        if qr_detections:
            return qr_detections

        # ── Layer 3: YOLO COCO fallback (any non-person object) ──
        model = self._get_model()
        results = model(frame, verbose=False)
        detections: list[Detection] = []
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                if conf < self._threshold:
                    continue
                if cls_id == PERSON_CLS_ID:
                    continue
                cls_name = COCO_NAMES.get(cls_id, f"object_{cls_id}")
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(
                    bbox=(float(x1), float(y1), float(x2), float(y2)),
                    score=conf,
                    cls_name=cls_name,
                ))
        return detections

    def observe(
        self,
        frame: np.ndarray,
        state: str = "SEARCH",
    ) -> Observation:
        """Run detection and build Observation summary (timestamp, detections, primary offset, confidence)."""
        detections = self.detect(frame)
        h, w = frame.shape[:2]
        offset = primary_detection_center_offset(w, detections)
        confidence = float(detections[0].score) if detections else 0.0
        return Observation(
            timestamp=time.monotonic(),
            state=state,
            persons=detections,  # "persons" field reused for all detections
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
