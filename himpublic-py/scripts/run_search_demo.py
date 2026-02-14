#!/usr/bin/env python3
"""Standalone demo runner for SearchForPersonPhase.

Uses webcam + microphone (if available) to demonstrate the search pipeline
without any robot hardware.

Renders a live window showing:
  - Current search state
  - Audio scan heading + confidence
  - Person detection bbox overlay
  - Key controls

Key controls:
  Q  → quit
  R  → force rescan (back to CALLOUT)
  M  → manual "found" override
  +  → raise detection threshold by 0.05
  -  → lower detection threshold by 0.05

Usage:
  python scripts/run_search_demo.py
  python scripts/run_search_demo.py --no-tts --webcam-index 1
  python scripts/run_search_demo.py --yolo-model yolov8s.pt --det-thresh 0.4
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

# Add src to path so we can import himpublic
_script_dir = Path(__file__).resolve().parent
_src_dir = _script_dir.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from himpublic.orchestrator.search_phase import (
    SearchForPersonPhase,
    SearchPhaseConfig,
    SearchResult,
    SearchState,
    RobotActions,
)
from himpublic.utils.event_logger import SearchEventLogger
from himpublic.utils.logging import setup_logging

logger = logging.getLogger(__name__)

# ── Try to import detector for overlay ───────────────────────────────
_HAS_DRAW = False
try:
    from himpublic.perception.person_detector import draw_boxes
    _HAS_DRAW = True
except ImportError:
    draw_boxes = None  # type: ignore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search-for-person demo (webcam + mic)")
    p.add_argument("--webcam-index", type=int, default=0, help="Webcam device index")
    p.add_argument("--yolo-model", type=str, default="yolov8n.pt", help="YOLO model")
    p.add_argument("--det-thresh", type=float, default=0.45, help="Detection threshold")
    p.add_argument("--no-tts", action="store_true", help="Disable TTS (print only)")
    p.add_argument("--audio-step-deg", type=float, default=30.0, help="Audio scan step degrees")
    p.add_argument("--audio-delay", type=float, default=0.5, help="Delay between audio scan steps (s)")
    p.add_argument("--log-level", type=str, default="INFO", help="Log level")
    p.add_argument("--evidence-dir", type=str, default="data/search_evidence", help="Evidence output dir")
    return p.parse_args()


class DemoOverlay:
    """Thread-safe state container for the preview overlay."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.search_state: str = "INIT"
        self.heading_deg: float = 0.0
        self.audio_confidence: float = 0.0
        self.det_threshold: float = 0.45
        self.person_confidence: float = 0.0
        self.person_area_frac: float = 0.0
        self.found: bool | None = None  # None = still running
        self.detections: list = []

    def update(self, **kwargs: object) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "search_state": self.search_state,
                "heading_deg": self.heading_deg,
                "audio_confidence": self.audio_confidence,
                "det_threshold": self.det_threshold,
                "person_confidence": self.person_confidence,
                "person_area_frac": self.person_area_frac,
                "found": self.found,
                "detections": list(self.detections),
            }


def draw_overlay(frame: np.ndarray, info: dict) -> np.ndarray:
    """Draw HUD overlay on the preview frame."""
    out = frame.copy()
    h, w = out.shape[:2]

    # Semi-transparent top bar
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, 130), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.7, out, 0.3, 0, out)

    y = 22
    state = info["search_state"]
    state_color = {
        "CALLOUT": (0, 200, 255),
        "AUDIO_SCAN": (255, 200, 0),
        "NAVIGATE": (255, 150, 0),
        "VISION_CONFIRM": (0, 255, 200),
        "APPROACH": (0, 255, 0),
        "DONE": (0, 255, 0) if info.get("found") else (0, 0, 255),
    }.get(state, (200, 200, 200))

    cv2.putText(out, f"State: {state}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, state_color, 2)
    y += 28
    cv2.putText(out, f"Heading: {info['heading_deg']:.0f} deg  Audio conf: {info['audio_confidence']:.2f}",
                (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += 22
    cv2.putText(out, f"Person conf: {info['person_confidence']:.2f}  Area: {info['person_area_frac']:.1%}",
                (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += 22
    cv2.putText(out, f"Det thresh: {info['det_threshold']:.2f}",
                (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # Result if done
    if info["found"] is not None:
        result_text = "FOUND!" if info["found"] else "NOT FOUND"
        result_color = (0, 255, 0) if info["found"] else (0, 0, 255)
        cv2.putText(out, result_text, (w // 2 - 80, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, result_color, 3)

    # Bottom help bar
    help_y = h - 12
    cv2.putText(out, "Q=quit  R=rescan  M=manual-found  +/-=threshold",
                (10, help_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

    # Draw detection boxes
    dets = info.get("detections", [])
    if _HAS_DRAW and draw_boxes is not None and dets:
        out = draw_boxes(out, dets)

    return out


def run_search_in_thread(
    phase: SearchForPersonPhase,
    overlay: DemoOverlay,
    result_holder: list,
) -> None:
    """Run the search phase in a background thread so the main thread can show the preview."""
    try:
        result = phase.run()
        result_holder.append(result)
        overlay.update(
            search_state="DONE",
            found=result.found,
            person_confidence=result.confidence,
            heading_deg=result.chosen_heading_deg,
            audio_confidence=result.audio_scan_result.confidence if result.audio_scan_result else 0.0,
        )
    except Exception as e:
        logger.error("Search phase error: %s", e, exc_info=True)
        result_holder.append(SearchResult(found=False, reason=f"error: {e}"))
        overlay.update(search_state="DONE", found=False)


def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    config = SearchPhaseConfig(
        audio_step_degrees=args.audio_step_deg,
        audio_delay_between_steps_s=args.audio_delay,
        audio_window_s=0.4,
        detection_threshold=args.det_thresh,
        yolo_model=args.yolo_model,
        mode="demo",
        use_tts=not args.no_tts,
        evidence_dir=args.evidence_dir,
    )

    logger.info("Opening webcam index=%d", args.webcam_index)
    cap = cv2.VideoCapture(args.webcam_index)
    if not cap.isOpened():
        print(f"ERROR: Cannot open webcam index {args.webcam_index}", file=sys.stderr)
        return 1

    event_logger = SearchEventLogger("logs/search_demo_events.jsonl")
    overlay = DemoOverlay()
    overlay.update(det_threshold=config.detection_threshold)

    # Create the search phase (pass raw cv2.VideoCapture)
    phase = SearchForPersonPhase(
        config=config,
        video_source=cap,
        robot_actions=RobotActions(mode="demo"),
        event_logger=event_logger,
    )

    # Monkey-patch the phase to update overlay on state transitions
    _orig_transition = phase._transition

    def _patched_transition(new_state: SearchState, reason: str = "") -> None:
        _orig_transition(new_state, reason)
        overlay.update(search_state=new_state.value)
        # Update heading/confidence if available
        if phase._result.audio_scan_result:
            overlay.update(
                heading_deg=phase._result.chosen_heading_deg,
                audio_confidence=phase._result.audio_scan_result.confidence,
            )
        overlay.update(
            person_confidence=phase._result.confidence,
            person_area_frac=phase._result.person_area_frac,
        )

    phase._transition = _patched_transition  # type: ignore[assignment]

    # Start search in background thread
    result_holder: list[SearchResult] = []
    search_thread = threading.Thread(
        target=run_search_in_thread,
        args=(phase, overlay, result_holder),
        daemon=True,
    )
    search_thread.start()
    overlay.update(search_state="CALLOUT")

    print("\n╔══════════════════════════════════════════╗")
    print("║  SearchForPerson Demo                    ║")
    print("║  Q=quit  R=rescan  M=manual-found        ║")
    print("║  +/- = adjust detection threshold        ║")
    print("╚══════════════════════════════════════════╝\n")

    # Main preview loop
    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.05)
                continue

            # Update detection overlay from the phase's live state
            if phase._detector is not None:
                try:
                    dets = phase._detector.detect(frame)
                    overlay.update(detections=dets)
                    if dets:
                        best = max(dets, key=lambda d: d.score)
                        area = (best.bbox[2] - best.bbox[0]) * (best.bbox[3] - best.bbox[1])
                        fh, fw = frame.shape[:2]
                        overlay.update(
                            person_confidence=best.score,
                            person_area_frac=area / (fw * fh) if fw * fh > 0 else 0,
                        )
                except Exception:
                    pass

            info = overlay.snapshot()
            display = draw_overlay(frame, info)
            cv2.imshow("SearchForPerson Demo", display)

            key = cv2.waitKey(30) & 0xFF
            if key == ord("q"):
                phase.request_stop()
                break
            elif key == ord("r"):
                # Force rescan: reset state
                phase._audio_retries = 0
                phase._transition(SearchState.CALLOUT, "user pressed R")  # type: ignore[arg-type]
            elif key == ord("m"):
                phase.mark_found_manual()
                overlay.update(found=True)
            elif key in (ord("+"), ord("=")):
                config.detection_threshold = min(0.95, config.detection_threshold + 0.05)
                if phase._detector:
                    phase._detector._threshold = config.detection_threshold
                overlay.update(det_threshold=config.detection_threshold)
                logger.info("Detection threshold: %.2f", config.detection_threshold)
            elif key in (ord("-"), ord("_")):
                config.detection_threshold = max(0.1, config.detection_threshold - 0.05)
                if phase._detector:
                    phase._detector._threshold = config.detection_threshold
                overlay.update(det_threshold=config.detection_threshold)
                logger.info("Detection threshold: %.2f", config.detection_threshold)

            # Check if search is done
            if result_holder:
                # Keep showing the result for a few seconds
                time.sleep(3)
                break

    except KeyboardInterrupt:
        phase.request_stop()
    finally:
        cap.release()
        cv2.destroyAllWindows()

    # Print summary
    if result_holder:
        result = result_holder[0]
        print("\n" + "=" * 50)
        print(f"Search Result: {'FOUND' if result.found else 'NOT FOUND'}")
        print(f"  Confidence: {result.confidence:.3f}")
        print(f"  Heading: {result.chosen_heading_deg:.0f} deg")
        if result.best_frame_before_approach_path:
            print(f"  Before-approach frame: {result.best_frame_before_approach_path}")
        if result.best_frame_closeup_path:
            print(f"  Closeup frame: {result.best_frame_closeup_path}")
        print(f"  Manual override: {result.manual_override}")
        print(f"  Reason: {result.reason}")
        print(f"  Event log: {event_logger.path}")
        print("=" * 50)
    else:
        print("\nSearch aborted.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
