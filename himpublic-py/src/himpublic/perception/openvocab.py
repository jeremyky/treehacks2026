"""Open-vocabulary rubble detection using YOLO-World.

Why not plain YOLOv8?
  YOLOv8 (COCO-80) only detects 80 fixed categories. "Cardboard box", "rubble",
  "debris", and "package" are NOT COCO classes. A plain Amazon box sitting on the
  floor will not be detected.

Why YOLO-World?
  YOLO-World extends YOLO with a vision-language backbone (RepVL-PAN) that lets
  you specify detection targets as free-form text prompts at inference time.
  It's built into the `ultralytics` package — zero extra installs.

  Example:
      model = YOLO("yolov8s-worldv2")
      model.set_classes(["cardboard box", "package", "rubble"])
      results = model(frame)

Fallback:
  If YOLO-World fails to load (e.g. model download fails, GPU OOM), the detector
  gracefully returns found=False rather than crashing the pipeline.

Fiducials (QR/AprilTag) are a robust backup and remain in person_detector.py as
a parallel path, but open-vocab detection is the primary method — it generalizes
to any rubble type without hard-coded markers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Default text prompts that YOLO-World will search for in each frame.
# Order matters: first match with highest score wins.
DEFAULT_RUBBLE_PROMPTS: list[str] = [
    "cardboard box",
    "amazon box",
    "package",
    "box",
    "debris",
    "rubble",
    "crate",
    "wooden pallet",
    "broken concrete",
    "pile of bricks",
]

# Detection thresholds
DEFAULT_CONFIDENCE_THRESHOLD = 0.15  # YOLO-World scores are typically lower than COCO YOLO
DEFAULT_MODEL_NAME = "yolov8s-worldv2"  # small model, good speed/accuracy balance


@dataclass
class RubbleDetection:
    """Structured output for a single rubble detection."""
    found: bool
    label: str
    score: float
    bbox_xyxy: tuple[float, float, float, float]  # x1, y1, x2, y2
    center_xy: tuple[float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "label": self.label,
            "score": round(self.score, 3),
            "bbox_xyxy": [round(v, 1) for v in self.bbox_xyxy],
            "center_xy": [round(v, 1) for v in self.center_xy],
        }


# Sentinel for "no detection"
NO_DETECTION = RubbleDetection(
    found=False, label="", score=0.0,
    bbox_xyxy=(0.0, 0.0, 0.0, 0.0), center_xy=(0.0, 0.0),
)


class OpenVocabDetector:
    """Open-vocabulary rubble detector using YOLO-World.

    Usage:
        detector = OpenVocabDetector()
        result = detector.detect(frame)
        if result.found:
            print(f"Rubble: {result.label} ({result.score:.2f})")

    The model is loaded lazily on first detect() call. If loading fails,
    all subsequent calls return NO_DETECTION (graceful degradation).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        prompts: list[str] | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._model_name = model_name
        self._prompts = prompts or DEFAULT_RUBBLE_PROMPTS
        self._confidence_threshold = confidence_threshold
        self._model: Any = None
        self._model_failed = False  # True if model load failed (don't retry)
        self._classes_set = False
        self._detect_count = 0
        self._last_log_time = 0.0

    def _load_model(self) -> bool:
        """Load YOLO-World model. Returns True on success."""
        if self._model_failed:
            return False
        if self._model is not None:
            return True
        try:
            from ultralytics import YOLO
            logger.info(
                "Loading YOLO-World model: %s (prompts: %s)",
                self._model_name,
                self._prompts[:5],
            )
            t0 = time.monotonic()
            self._model = YOLO(self._model_name)
            elapsed = time.monotonic() - t0
            logger.info("YOLO-World model loaded in %.1fs", elapsed)
            return True
        except Exception as e:
            logger.error(
                "Failed to load YOLO-World model %r: %s. "
                "Open-vocab detection disabled — falling back to QR/YOLO-COCO.",
                self._model_name, e,
            )
            self._model_failed = True
            return False

    def _ensure_classes(self) -> None:
        """Set text prompts on the model (only once)."""
        if self._classes_set or self._model is None:
            return
        try:
            self._model.set_classes(self._prompts)
            self._classes_set = True
            logger.info("YOLO-World classes set: %s", self._prompts)
        except Exception as e:
            logger.error("Failed to set YOLO-World classes: %s", e)

    @property
    def available(self) -> bool:
        """True if model is loaded and ready."""
        return self._model is not None and not self._model_failed

    @property
    def prompts(self) -> list[str]:
        return list(self._prompts)

    def detect(self, frame: np.ndarray) -> RubbleDetection:
        """Run open-vocab detection on a BGR frame.

        Returns the highest-confidence rubble detection, or NO_DETECTION.
        Thread-safe for single-writer (perception loop).
        """
        if not self._load_model():
            return NO_DETECTION
        self._ensure_classes()

        try:
            results = self._model(frame, verbose=False, conf=self._confidence_threshold)
        except Exception as e:
            logger.warning("YOLO-World inference failed: %s", e)
            return NO_DETECTION

        self._detect_count += 1
        best: RubbleDetection | None = None

        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                conf = float(box.conf[0])
                if conf < self._confidence_threshold:
                    continue
                cls_id = int(box.cls[0])
                # Map class id back to prompt label
                if cls_id < len(self._prompts):
                    label = self._prompts[cls_id]
                else:
                    label = f"rubble_{cls_id}"

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                det = RubbleDetection(
                    found=True,
                    label=label,
                    score=conf,
                    bbox_xyxy=(float(x1), float(y1), float(x2), float(y2)),
                    center_xy=(cx, cy),
                )
                if best is None or det.score > best.score:
                    best = det

        # Periodic logging (every 30 frames or when detection changes)
        now = time.monotonic()
        if best is not None:
            logger.info(
                "OpenVocab FOUND: %s (%.2f) at [%.0f,%.0f,%.0f,%.0f]",
                best.label, best.score, *best.bbox_xyxy,
            )
        elif now - self._last_log_time > 5.0:
            logger.debug(
                "OpenVocab: no rubble in frame #%d (prompts: %s)",
                self._detect_count, self._prompts[:3],
            )
            self._last_log_time = now

        return best if best is not None else NO_DETECTION

    def detect_all(self, frame: np.ndarray) -> list[RubbleDetection]:
        """Return ALL detections (not just the best). Useful for visualization."""
        if not self._load_model():
            return []
        self._ensure_classes()

        try:
            results = self._model(frame, verbose=False, conf=self._confidence_threshold)
        except Exception as e:
            logger.warning("YOLO-World inference failed: %s", e)
            return []

        detections: list[RubbleDetection] = []
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                conf = float(box.conf[0])
                if conf < self._confidence_threshold:
                    continue
                cls_id = int(box.cls[0])
                label = self._prompts[cls_id] if cls_id < len(self._prompts) else f"rubble_{cls_id}"
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                detections.append(RubbleDetection(
                    found=True, label=label, score=conf,
                    bbox_xyxy=(float(x1), float(y1), float(x2), float(y2)),
                    center_xy=(cx, cy),
                ))
        detections.sort(key=lambda d: d.score, reverse=True)
        return detections
