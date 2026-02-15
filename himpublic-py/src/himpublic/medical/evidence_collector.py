"""
EvidenceCollector — burst capture, sharpest-frame selection, annotation, and saving.

Responsibilities:
  1. Maintain a rolling buffer of the last N frames.
  2. On ``collect(findings)``: pick sharpest frame, save full / crop / annotated.
  3. Fill each Finding's ``evidence`` field with relative paths.

All I/O is best-effort: failures are logged but never crash the pipeline.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .schemas import EvidencePaths, Finding

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_BUFFER_SIZE = 60   # ~30s at 2 fps — enough to pick diverse angles
MAX_VIEWS = 6              # max screenshots to save; avoid too many from same angle
MIN_VIEW_DIVERSITY = 0.25  # min histogram distance (0–1) to count as different angle
CROP_MARGIN_FRAC = 0.15          # 15 % margin around bbox for crops
ANNOTATION_FONT = cv2.FONT_HERSHEY_SIMPLEX
ANNOTATION_FONT_SCALE = 0.55
ANNOTATION_THICKNESS = 2

# Severity → bbox colour (BGR)
_SEVERITY_COLOUR: dict[str, tuple[int, int, int]] = {
    "high":   (0, 0, 255),     # red
    "medium": (0, 165, 255),   # orange
    "low":    (0, 255, 255),   # yellow
}


def _sharpness(frame: np.ndarray) -> float:
    """Variance of Laplacian — higher = sharper."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _frame_descriptor(frame: np.ndarray, size: int = 32) -> np.ndarray:
    """Compact descriptor for diversity: downscale and flatten (for L2 distance)."""
    small = cv2.resize(frame, (size, size), interpolation=cv2.INTER_AREA)
    return small.astype(np.float32).flatten()


def _descriptor_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized L2 distance in [0, 1]. Higher = more different."""
    d = np.linalg.norm(a - b)
    return float(min(1.0, d / (a.size ** 0.5 * 255)))


def _safe_mkdir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("Could not create directory %s: %s", p, e)


def _safe_imwrite(path: str, img: np.ndarray) -> bool:
    try:
        cv2.imwrite(path, img)
        return True
    except Exception as e:
        logger.warning("Failed to write image %s: %s", path, e)
        return False


def _blur_face_region(frame: np.ndarray, pose_results: Any | None = None) -> np.ndarray:
    """
    Best-effort face blur.  Uses a Haar cascade (ships with OpenCV).
    If no face found, returns frame unchanged.
    """
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"  # type: ignore[attr-defined]
        cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
        out = frame.copy()
        for (fx, fy, fw, fh) in faces:
            roi = out[fy : fy + fh, fx : fx + fw]
            blurred = cv2.GaussianBlur(roi, (99, 99), 30)
            out[fy : fy + fh, fx : fx + fw] = blurred
        return out
    except Exception:
        return frame


class EvidenceCollector:
    """
    Rolling-buffer frame collector with burst capture + annotation.

    Usage::

        collector = EvidenceCollector(output_dir="reports/evidence")
        collector.push_frame(frame_bgr)        # call per-frame
        collector.collect(findings)             # when findings exist
    """

    def __init__(
        self,
        output_dir: str | Path = "reports/evidence",
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        max_views: int = MAX_VIEWS,
        min_view_diversity: float = MIN_VIEW_DIVERSITY,
        blur_faces: bool = True,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._buffer: deque[np.ndarray] = deque(maxlen=buffer_size)
        self._max_views = max(1, max_views)
        self._min_view_diversity = min_view_diversity
        self._blur_faces = blur_faces

    # ── Frame buffer ──────────────────────────────────────────
    def push_frame(self, frame_bgr: np.ndarray) -> None:
        """Add a frame to the rolling buffer."""
        if frame_bgr is not None and frame_bgr.size > 0:
            self._buffer.append(frame_bgr.copy())

    @property
    def buffer_count(self) -> int:
        return len(self._buffer)

    def _select_diverse_frames(self) -> list[tuple[np.ndarray, float]]:
        """
        Select up to max_views frames that are sharp and diverse (not all same angle).
        Returns list of (frame, sharpness) with best frame first.
        """
        if not self._buffer:
            return []
        # Score each frame by sharpness
        scored = [(f, _sharpness(f)) for f in self._buffer]
        scored.sort(key=lambda x: -x[1])  # sharpest first
        selected: list[tuple[np.ndarray, float]] = []
        descriptors: list[np.ndarray] = []
        for frame, sharp in scored:
            if len(selected) >= self._max_views:
                break
            desc = _frame_descriptor(frame)
            # Keep only if sufficiently different from already selected
            if not selected:
                selected.append((frame, sharp))
                descriptors.append(desc)
            else:
                min_dist = min(_descriptor_distance(desc, d) for d in descriptors)
                if min_dist >= self._min_view_diversity:
                    selected.append((frame, sharp))
                    descriptors.append(desc)
        return selected

    # ── Collect evidence ──────────────────────────────────────
    def collect(
        self,
        findings: list[Finding],
        victim_id: str | None = None,
    ) -> Path | None:
        """
        Save multiple scene views (diverse angles) plus crops/annotated from best frame.
        CV/robot: take a lot of screenshots but not too many from the same angle.
        """
        if not findings:
            return None
        if not self._buffer:
            logger.warning("EvidenceCollector: buffer empty — cannot collect evidence.")
            return None

        # ── select diverse frames (sharp + different from each other) ─────
        diverse = self._select_diverse_frames()
        if not diverse:
            diverse = [(self._buffer[-1], _sharpness(self._buffer[-1]))]
        best_frame, best_sharpness = diverse[0]

        # ── build output dir ──────────────────────────────────
        ts = time.strftime("%Y%m%d_%H%M%S")
        label = f"victim_{victim_id}" if victim_id else ts
        evidence_dir = self._output_dir / label
        _safe_mkdir(evidence_dir)

        # ── save multiple full images (views) so report has variety ───────
        for i, (view_frame, _) in enumerate(diverse):
            full_path = evidence_dir / f"full_{i + 1}.jpg"
            _safe_imwrite(str(full_path), view_frame)
        # Primary full image for report links (same as first view)
        full_path = evidence_dir / "full.jpg"
        _safe_imwrite(str(full_path), best_frame)

        h, w = best_frame.shape[:2]

        for k, finding in enumerate(findings):
            # ── crop with margin ──────────────────────────────
            x1, y1, x2, y2 = finding.bbox_xyxy
            bw, bh = x2 - x1, y2 - y1
            mx = int(bw * CROP_MARGIN_FRAC)
            my = int(bh * CROP_MARGIN_FRAC)
            cx1 = max(0, x1 - mx)
            cy1 = max(0, y1 - my)
            cx2 = min(w, x2 + mx)
            cy2 = min(h, y2 + my)
            crop = best_frame[cy1:cy2, cx1:cx2]

            crop_path = evidence_dir / f"finding_{k}_crop.jpg"
            if crop.size > 0:
                _safe_imwrite(str(crop_path), crop)

            # ── annotated image ───────────────────────────────
            annot = best_frame.copy()
            if self._blur_faces:
                annot = _blur_face_region(annot)

            colour = _SEVERITY_COLOUR.get(finding.severity, (255, 255, 255))
            cv2.rectangle(annot, (x1, y1), (x2, y2), colour, ANNOTATION_THICKNESS)

            # Label: "likely bleeding (0.62) left_lower_leg"
            text = f"{finding.label} ({finding.confidence:.2f}) {finding.body_region}"
            (tw, th), _ = cv2.getTextSize(text, ANNOTATION_FONT, ANNOTATION_FONT_SCALE, ANNOTATION_THICKNESS)
            # Background rectangle for text
            txt_y = max(y1 - 6, th + 4)
            cv2.rectangle(annot, (x1, txt_y - th - 4), (x1 + tw + 4, txt_y + 4), colour, -1)
            cv2.putText(
                annot, text,
                (x1 + 2, txt_y),
                ANNOTATION_FONT, ANNOTATION_FONT_SCALE,
                (0, 0, 0), ANNOTATION_THICKNESS, cv2.LINE_AA,
            )

            annot_path = evidence_dir / f"finding_{k}_annot.jpg"
            _safe_imwrite(str(annot_path), annot)

            # ── fill evidence paths ───────────────────────────
            finding.evidence = EvidencePaths(
                full_image=str(full_path.relative_to(self._output_dir.parent) if self._output_dir.parent.exists() else full_path),
                crop_image=str(crop_path.relative_to(self._output_dir.parent) if self._output_dir.parent.exists() else crop_path),
                annotated_image=str(annot_path.relative_to(self._output_dir.parent) if self._output_dir.parent.exists() else annot_path),
            )

        logger.info(
            "EvidenceCollector: saved %d view(s) + %d finding(s) to %s (sharpness=%.1f)",
            len(diverse), len(findings), evidence_dir, best_sharpness,
        )
        return evidence_dir
