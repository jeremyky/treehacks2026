"""Image annotator: draw bboxes, injury labels; save annotated image; injury crop stub."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .types import Detection, InjuryFinding

try:
    import cv2
    import numpy as np
    _HAS_CV = True
except ImportError:
    _HAS_CV = False


def draw_detections(image: Any, detections: list[Detection], color: tuple = (0, 255, 0), thickness: int = 2) -> Any:
    """Draw bounding boxes and labels on image. Returns annotated image (copy)."""
    if not _HAS_CV:
        return image
    out = image.copy()
    for d in detections:
        if d.bbox is None:
            continue
        x1, y1, x2, y2 = [int(v) for v in d.bbox]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
        label = f"person {d.confidence:.2f}"
        cv2.putText(out, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return out


def draw_injury_labels(
    image: Any,
    injuries: list[InjuryFinding],
    bboxes: list[tuple[float, float, float, float]] | None = None,
    color: tuple = (0, 0, 255),
    thickness: int = 2,
) -> Any:
    """Draw injury region labels. If bboxes provided, one per injury; else center crop stub area."""
    if not _HAS_CV:
        return image
    out = image.copy()
    h, w = out.shape[:2]
    for i, inj in enumerate(injuries):
        if bboxes and i < len(bboxes):
            x1, y1, x2, y2 = [int(v) for v in bboxes[i]]
        else:
            # Stub: center region
            cx, cy = w // 2, h // 2
            sz = min(w, h) // 4
            x1, y1 = max(0, cx - sz), max(0, cy - sz)
            x2, y2 = min(w, cx + sz), min(h, cy + sz)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
        label = f"{inj.type} {inj.body_region} ({inj.severity})"
        cv2.putText(out, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    return out


def annotate_image(
    image_rgb: Any,
    detections: list[Detection] | None = None,
    injuries: list[InjuryFinding] | None = None,
    injury_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> Any:
    """Produce one annotated image: person bboxes + injury labels."""
    if not _HAS_CV:
        return image_rgb
    out = image_rgb.copy()
    if detections:
        out = draw_detections(out, detections)
    if injuries:
        out = draw_injury_labels(out, injuries, injury_bboxes)
    return out


def crop_injury_region(
    image: Any,
    bbox: tuple[float, float, float, float] | None = None,
) -> Any:
    """Crop injury region. If bbox absent, center crop stub (e.g. 1/4 of image)."""
    if not _HAS_CV:
        return image
    h, w = image.shape[:2]
    if bbox is not None:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
    else:
        cx, cy = w // 2, h // 2
        sz = min(w, h) // 4
        x1 = max(0, cx - sz)
        y1 = max(0, cy - sz)
        x2 = min(w, cx + sz)
        y2 = min(h, cy + sz)
    return image[y1:y2, x1:x2]


def save_annotated_image(
    image_rgb: Any,
    path: str | Path,
    detections: list[Detection] | None = None,
    injuries: list[InjuryFinding] | None = None,
    injury_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> None:
    """Draw detections + injuries on image and save to path."""
    if not _HAS_CV:
        Path(path).write_bytes(b"")
        return
    out = annotate_image(image_rgb, detections, injuries, injury_bboxes)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(out, cv2.COLOR_RGB2BGR) if len(out.shape) == 3 else out)
