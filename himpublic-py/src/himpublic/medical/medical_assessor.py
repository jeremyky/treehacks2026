"""
MedicalAssessor — CV-based injury-cue detection (triage support, NOT diagnosis).

Components:
  A) Pose / body-region estimation  (MediaPipe Pose, optional)
  B) Open-vocabulary detection       (YOLO-World, reuses existing OpenVocabDetector)
  C) Redness / blood-like heuristic  (HSV mask)
  D) Score fusion + severity mapping
  E) Output: list[Finding]

Gracefully degrades when optional dependencies are missing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import cv2
import numpy as np

from .schemas import Finding, FindingType, SeverityLevel

logger = logging.getLogger(__name__)

# ── Injury-cue prompts for YOLO-World ────────────────────────────────────
# Include "red tape" / "red bandage" for hackathon demo (simulated injury with tape).
DEFAULT_INJURY_PROMPTS: list[str] = [
    "blood",
    "bleeding",
    "open wound",
    "cut",
    "bruise",
    "burn",
    "bandage",
    "red tape",
    "red bandage",
    "tape",
    "injury",
]

# Map prompt substring → finding_type
_PROMPT_TO_TYPE: dict[str, FindingType] = {
    "blood":    "suspected_bleeding",
    "bleeding": "suspected_bleeding",
    "wound":    "suspected_wound",
    "cut":      "suspected_wound",
    "bruise":   "suspected_bruise",
    "burn":     "suspected_burn",
    "bandage":  "suspected_wound",
    "tape":     "suspected_wound",
    "injury":   "unknown",
}

# ── HSV red-mask thresholds ──────────────────────────────────────────────
# Red wraps around hue=0/180, so we use two ranges.
_RED_LOWER1 = np.array([0, 70, 50])
_RED_UPPER1 = np.array([10, 255, 255])
_RED_LOWER2 = np.array([170, 70, 50])
_RED_UPPER2 = np.array([180, 255, 255])


def _compute_red_ratio(crop_bgr: np.ndarray) -> float:
    """Fraction of pixels in a crop that fall within red-ish HSV thresholds."""
    if crop_bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, _RED_LOWER1, _RED_UPPER1)
    mask2 = cv2.inRange(hsv, _RED_LOWER2, _RED_UPPER2)
    red_pixels = int(cv2.countNonZero(mask1) + cv2.countNonZero(mask2))
    total = hsv.shape[0] * hsv.shape[1]
    return red_pixels / max(total, 1)


def _prompt_to_finding_type(prompt: str) -> FindingType:
    lower = prompt.lower()
    for key, ftype in _PROMPT_TO_TYPE.items():
        if key in lower:
            return ftype
    return "unknown"


def _fuse_confidence(openvocab_score: float, red_ratio: float) -> float:
    """Weighted fusion: 75 % open-vocab score + 25 % normalised red ratio."""
    norm_red = min(red_ratio / 0.20, 1.0)  # 20 % red → 1.0
    raw = 0.75 * openvocab_score + 0.25 * norm_red
    return max(0.0, min(1.0, raw))


def _map_severity(finding_type: FindingType, confidence: float, red_ratio: float) -> SeverityLevel:
    if finding_type == "suspected_bleeding":
        if red_ratio > 0.10 or confidence > 0.75:
            return "high"
        return "medium"
    # bruise / burn / wound
    if confidence > 0.55:
        return "medium"
    return "low"


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.70:
        return "very likely"
    if confidence >= 0.45:
        return "likely"
    return "possible"


# ── Pose helper (MediaPipe) ──────────────────────────────────────────────

_POSE_AVAILABLE = False
_pose_model: Any = None

try:
    import mediapipe as mp
    _POSE_AVAILABLE = True
except ImportError:
    mp = None  # type: ignore[assignment]


# Landmark indices (MediaPipe Pose)
_BODY_REGION_MAP: dict[str, list[int]] = {
    "head":            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "left_shoulder":   [11],
    "right_shoulder":  [12],
    "left_upper_arm":  [13],
    "right_upper_arm": [14],
    "left_forearm":    [15],
    "right_forearm":   [16],
    "left_hand":       [17, 19, 21],
    "right_hand":      [18, 20, 22],
    "torso":           [11, 12, 23, 24],
    "left_upper_leg":  [23, 25],
    "right_upper_leg": [24, 26],
    "left_lower_leg":  [25, 27, 29, 31],
    "right_lower_leg": [26, 28, 30, 32],
}


def _get_pose(frame_bgr: np.ndarray) -> Any | None:
    """Run MediaPipe Pose, return results or None."""
    global _pose_model
    if not _POSE_AVAILABLE:
        return None
    try:
        if _pose_model is None:
            _pose_model = mp.solutions.pose.Pose(  # type: ignore[union-attr]
                static_image_mode=False,
                model_complexity=0,
                min_detection_confidence=0.5,
            )
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return _pose_model.process(rgb)
    except Exception as e:
        logger.debug("Pose estimation failed: %s", e)
        return None


def infer_body_region(
    bbox_center: tuple[float, float],
    pose_results: Any | None,
    frame_shape: tuple[int, ...],
) -> str:
    """Map a bbox center to the nearest body region using pose landmarks."""
    if pose_results is None or not hasattr(pose_results, "pose_landmarks"):
        return "unknown"
    landmarks = pose_results.pose_landmarks
    if landmarks is None:
        return "unknown"

    h, w = frame_shape[:2]
    cx, cy = bbox_center

    best_region = "unknown"
    best_dist = float("inf")

    for region, indices in _BODY_REGION_MAP.items():
        for idx in indices:
            if idx >= len(landmarks.landmark):
                continue
            lm = landmarks.landmark[idx]
            lx, ly = lm.x * w, lm.y * h
            dist = ((cx - lx) ** 2 + (cy - ly) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_region = region

    return best_region


# ── Main Assessor ────────────────────────────────────────────────────────

class MedicalAssessor:
    """
    Per-frame injury-cue detection using open-vocab CV + colour heuristic + pose.

    Usage::

        assessor = MedicalAssessor()
        findings = assessor.assess(frame_bgr)
        for f in findings:
            print(f.label, f.confidence, f.body_region)
    """

    def __init__(
        self,
        prompts: list[str] | None = None,
        confidence_threshold: float = 0.01,
        use_pose: bool = True,
    ) -> None:
        self._prompts = prompts or DEFAULT_INJURY_PROMPTS
        self._confidence_threshold = confidence_threshold
        self._use_pose = use_pose
        self._detector: Any = None
        self._detector_failed = False
        self._assess_count = 0
        self._last_log_time = 0.0

    # ── lazy load ─────────────────────────────────────────────
    def _load_detector(self) -> bool:
        if self._detector_failed:
            return False
        if self._detector is not None:
            return True
        try:
            from himpublic.perception.openvocab import OpenVocabDetector
            self._detector = OpenVocabDetector(
                prompts=self._prompts,
                confidence_threshold=self._confidence_threshold,
            )
            return True
        except Exception as e:
            logger.warning("Could not load open-vocab detector for injury cues: %s", e)
            self._detector_failed = True
            return False

    # ── main entry point ──────────────────────────────────────
    def assess(self, frame_bgr: np.ndarray) -> list[Finding]:
        """
        Analyse one BGR frame and return a list of suspected injury Findings.

        Never raises; returns [] on any error.
        """
        self._assess_count += 1
        findings: list[Finding] = []

        if frame_bgr is None or frame_bgr.size == 0:
            return findings

        # A) Pose
        pose_results = _get_pose(frame_bgr) if self._use_pose else None

        # B) Open-vocab detection
        detections = self._detect_candidates(frame_bgr)

        h, w = frame_bgr.shape[:2]

        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

            # Crop for redness heuristic
            x1i, y1i = max(0, int(x1)), max(0, int(y1))
            x2i, y2i = min(w, int(x2)), min(h, int(y2))
            crop = frame_bgr[y1i:y2i, x1i:x2i]

            # C) Redness heuristic
            red_ratio = _compute_red_ratio(crop) if crop.size > 0 else 0.0

            # D) Score fusion
            fused = _fuse_confidence(det["score"], red_ratio)
            finding_type = _prompt_to_finding_type(det["prompt"])
            severity = _map_severity(finding_type, fused, red_ratio)
            label = f"{_confidence_label(fused)} {finding_type.replace('suspected_', '')}"

            # Body region
            body_region = infer_body_region((cx, cy), pose_results, frame_bgr.shape)

            findings.append(Finding(
                finding_type=finding_type,
                label=label,
                confidence=fused,
                severity=severity,
                body_region=body_region,
                bbox_xyxy=[int(x1), int(y1), int(x2), int(y2)],
                prompt=det["prompt"],
                signals={
                    "openvocab_score": round(det["score"], 3),
                    "red_ratio": round(red_ratio, 4),
                    "pose_available": pose_results is not None,
                },
            ))

        # Rate-limited logging
        now = time.monotonic()
        if findings:
            logger.info(
                "MedicalAssessor: %d finding(s) in frame #%d — %s",
                len(findings),
                self._assess_count,
                [(f.label, f.confidence) for f in findings[:3]],
            )
        elif now - self._last_log_time > 10.0:
            logger.debug("MedicalAssessor: no findings in frame #%d", self._assess_count)
            self._last_log_time = now

        return findings

    # ── internal: open-vocab candidates ───────────────────────
    def _detect_candidates(self, frame_bgr: np.ndarray) -> list[dict[str, Any]]:
        """Return list of {prompt, score, bbox} dicts."""
        if not self._load_detector():
            return []
        try:
            all_dets = self._detector.detect_all(frame_bgr)
            return [
                {
                    "prompt": d.label,
                    "score": d.score,
                    "bbox": list(d.bbox_xyxy),
                }
                for d in all_dets
            ]
        except Exception as e:
            logger.warning("Open-vocab injury detection failed: %s", e)
            return []
