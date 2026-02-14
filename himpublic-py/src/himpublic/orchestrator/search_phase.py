"""SearchForPersonPhase: state machine for the SEARCHING part of the demo pipeline.

Sub-states:
  CALLOUT       → TTS "Where are you? Please shout."
  AUDIO_SCAN    → 360° mic scan to pick a heading
  NAVIGATE      → Turn toward heading, move forward (with vision + audio)
  VISION_CONFIRM → Person detection, confirm visually
  APPROACH      → Move closer until person fills frame or distance threshold
  DONE          → Return structured result

Supports two execution modes:
  - "demo"  (laptop): webcam + mic, virtual angles, no real motion
  - "robot" : calls placeholder robot action functions

Gracefully degrades when optional deps are missing.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from himpublic.perception.audio_scanner import AudioScanner, AudioScanResult
from himpublic.perception.types import Detection, Observation
from himpublic.utils.event_logger import SearchEventLogger

logger = logging.getLogger(__name__)

# ── Try to import person detector (needs ultralytics) ────────────────
_HAS_DETECTOR = False
try:
    from himpublic.perception.person_detector import PersonDetector, draw_boxes
    _HAS_DETECTOR = True
except ImportError:
    PersonDetector = None  # type: ignore
    draw_boxes = None  # type: ignore


# ── Sub-state enum ───────────────────────────────────────────────────
class SearchState(str, Enum):
    CALLOUT = "CALLOUT"
    AUDIO_SCAN = "AUDIO_SCAN"
    NAVIGATE = "NAVIGATE"
    VISION_CONFIRM = "VISION_CONFIRM"
    APPROACH = "APPROACH"
    DONE = "DONE"


# ── Result type ──────────────────────────────────────────────────────
@dataclass
class SearchResult:
    """Structured result returned when the search phase completes."""
    found: bool = False
    confidence: float = 0.0
    chosen_heading_deg: float = 0.0
    audio_scan_result: AudioScanResult | None = None
    best_frame_before_approach_path: str | None = None
    best_frame_closeup_path: str | None = None
    best_detection: Detection | None = None
    person_area_frac: float = 0.0
    reason: str = ""
    manual_override: bool = False

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "confidence": round(self.confidence, 3),
            "chosen_heading_deg": round(self.chosen_heading_deg, 1),
            "audio_scan": self.audio_scan_result.to_dict() if self.audio_scan_result else None,
            "best_frame_before_approach": self.best_frame_before_approach_path,
            "best_frame_closeup": self.best_frame_closeup_path,
            "person_area_frac": round(self.person_area_frac, 4),
            "reason": self.reason,
            "manual_override": self.manual_override,
        }


# ── Config for search phase ─────────────────────────────────────────
@dataclass
class SearchPhaseConfig:
    """Tunable parameters for SearchForPersonPhase."""
    # Audio scan
    audio_step_degrees: float = 30.0
    audio_window_s: float = 0.4
    audio_delay_between_steps_s: float = 0.5
    audio_min_confidence: float = 0.15  # below this → "can't hear you"

    # Vision confirm
    detection_threshold: float = 0.45
    yolo_model: str = "yolov8n.pt"
    vision_confirm_timeout_s: float = 10.0

    # Approach
    approach_person_area_target: float = 0.20  # 20% of frame area
    approach_depth_stop_m: float = 1.5
    approach_step_forward_s: float = 0.3  # how long to move forward per step
    approach_timeout_s: float = 30.0

    # Retries / timeouts
    max_audio_retries: int = 3
    callout_text: str = "Where are you? Please shout so I can find you!"
    retry_callout_text: str = "I can't hear you. Please shout again!"
    no_detection_rescan_s: float = 8.0  # after this long with no person, rescan audio

    # Evidence
    evidence_dir: str = "data/search_evidence"

    # Modes
    mode: str = "demo"  # "demo" or "robot"
    use_tts: bool = True


# ── Robot action stubs (for interface) ───────────────────────────────
class RobotActions:
    """Wrapper around robot motion.  In demo mode these are no-ops with logging."""

    def __init__(self, mode: str = "demo", robot: Any = None) -> None:
        self._mode = mode
        self._robot = robot

    def say(self, text: str) -> None:
        """TTS or print fallback."""
        logger.info("[SAY] %s", text)
        if self._mode == "robot" and self._robot is not None:
            try:
                self._robot.play_tts(text)
                return
            except Exception as e:
                logger.warning("Robot TTS failed: %s", e)
        # Fallback: try pyttsx3 / macOS say / print
        try:
            from himpublic.io.audio_io import LocalAudioIO
            LocalAudioIO(use_tts=True, use_mic=False).speak(text)
        except Exception:
            print(f"[TTS] {text}", flush=True)

    def turn_degrees(self, degrees: float) -> None:
        """Turn robot by degrees (positive = left). In demo mode: log only."""
        if self._mode == "robot" and self._robot is not None:
            # Duration estimate: ~45 deg/s at wz=0.5
            wz = 0.5 if degrees > 0 else -0.5
            dur = abs(degrees) / 45.0
            self._robot.set_velocity(0.0, wz)
            time.sleep(dur)
            self._robot.stop()
        else:
            logger.debug("[DEMO] turn %.1f deg", degrees)

    def move_forward(self, duration_s: float = 0.3) -> None:
        """Move robot forward briefly. In demo mode: log only."""
        if self._mode == "robot" and self._robot is not None:
            self._robot.set_velocity(0.2, 0.0)
            time.sleep(duration_s)
            self._robot.stop()
        else:
            logger.debug("[DEMO] move forward %.1fs", duration_s)

    def stop(self) -> None:
        if self._mode == "robot" and self._robot is not None:
            self._robot.stop()


# ── Main phase class ─────────────────────────────────────────────────
class SearchForPersonPhase:
    """State machine for searching for a person.

    Usage (from orchestrator):
        phase = SearchForPersonPhase(config, video_source=cap, robot_actions=actions)
        result = phase.run()
        if result.found:
            # transition to next phase
    """

    def __init__(
        self,
        config: SearchPhaseConfig | None = None,
        video_source: Any = None,
        robot_actions: RobotActions | None = None,
        event_logger: SearchEventLogger | None = None,
        person_detector: Any = None,
    ) -> None:
        self.cfg = config or SearchPhaseConfig()
        self._video = video_source  # cv2.VideoCapture or BaseVideoSource (has .read())
        self._actions = robot_actions or RobotActions(mode=self.cfg.mode)
        self._log = event_logger or SearchEventLogger()
        self._state = SearchState.CALLOUT
        self._result = SearchResult()
        self._audio_retries = 0
        self._stop_requested = False
        self._manual_found = False

        # Person detector (lazy init)
        self._detector = person_detector
        if self._detector is None and _HAS_DETECTOR and PersonDetector is not None:
            try:
                self._detector = PersonDetector(
                    model_path=self.cfg.yolo_model,
                    threshold=self.cfg.detection_threshold,
                )
            except Exception as e:
                logger.warning("PersonDetector init failed: %s — vision will be disabled", e)

        # Evidence directory
        self._evidence_dir = Path(self.cfg.evidence_dir)
        self._evidence_dir.mkdir(parents=True, exist_ok=True)

        # Key state for approach
        self._last_detection_time: float = 0.0
        self._best_confidence: float = 0.0
        self._best_frame: np.ndarray | None = None

    def request_stop(self) -> None:
        self._stop_requested = True

    def mark_found_manual(self) -> None:
        """Manual override: mark person as found (for demo resilience)."""
        self._manual_found = True
        self._log.log_manual_override("M")

    @property
    def state(self) -> SearchState:
        return self._state

    def _transition(self, new_state: SearchState, reason: str = "") -> None:
        old = self._state
        self._state = new_state
        self._log.log_state_transition(old.value, new_state.value, reason)
        logger.info("Search state: %s → %s%s", old.value, new_state.value, f" ({reason})" if reason else "")

    def _read_frame(self) -> np.ndarray | None:
        """Read a frame from the video source."""
        if self._video is None:
            return None
        try:
            # Support both cv2.VideoCapture and BaseVideoSource
            if hasattr(self._video, "read"):
                result = self._video.read()
                if isinstance(result, tuple):
                    ret, frame = result
                    return frame if ret else None
                return result  # BaseVideoSource returns np.ndarray | None
        except Exception as e:
            logger.warning("Frame read failed: %s", e)
        return None

    def _detect_persons(self, frame: np.ndarray) -> list[Detection]:
        """Run person detection on a frame."""
        if self._detector is None:
            return []
        try:
            return self._detector.detect(frame)
        except Exception as e:
            logger.warning("Detection failed: %s", e)
            return []

    def _person_area_fraction(self, det: Detection, frame_shape: tuple) -> float:
        """Fraction of frame area occupied by person bbox."""
        h, w = frame_shape[:2]
        if h <= 0 or w <= 0:
            return 0.0
        bw = det.bbox[2] - det.bbox[0]
        bh = det.bbox[3] - det.bbox[1]
        return (bw * bh) / (w * h)

    def _save_frame(self, frame: np.ndarray, label: str) -> str:
        """Save frame as evidence and return the path."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        name = f"{label}_{ts}.jpg"
        path = self._evidence_dir / name
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        self._log.log_frame_saved(label, str(path))
        logger.info("Saved evidence frame: %s", path)
        return str(path)

    # ── State handlers ───────────────────────────────────────────────

    def _run_callout(self) -> None:
        """CALLOUT: announce and ask for a shout."""
        text = self.cfg.callout_text if self._audio_retries == 0 else self.cfg.retry_callout_text
        if self.cfg.use_tts:
            self._actions.say(text)
        else:
            print(f"[CALLOUT] {text}", flush=True)
        time.sleep(0.5)  # brief pause after callout
        self._transition(SearchState.AUDIO_SCAN, "callout complete")

    def _run_audio_scan(self) -> None:
        """AUDIO_SCAN: 360° mic scan to find loudest direction."""
        scanner = AudioScanner(
            step_degrees=self.cfg.audio_step_degrees,
            window_duration_s=self.cfg.audio_window_s,
            on_sample=lambda s: self._log.log_audio_sample(s.to_dict()),
        )
        self._log.log_audio_scan_start(
            int(360 / self.cfg.audio_step_degrees),
            self.cfg.audio_step_degrees,
        )

        if self.cfg.mode == "robot":
            scan_result = scanner.scan_robot(
                turn_fn=self._actions.turn_degrees,
                stop_fn=self._actions.stop,
                stop_check=lambda: self._stop_requested,
            )
        else:
            scan_result = scanner.scan_demo(
                delay_between_steps_s=self.cfg.audio_delay_between_steps_s,
                stop_check=lambda: self._stop_requested,
            )

        self._log.log_audio_scan_result(scan_result.to_dict())
        self._result.audio_scan_result = scan_result
        self._result.chosen_heading_deg = scan_result.chosen_angle_deg

        if scan_result.confidence < self.cfg.audio_min_confidence:
            self._audio_retries += 1
            if self._audio_retries >= self.cfg.max_audio_retries:
                # Give up on audio, proceed anyway with best guess
                self._log.log_fallback("audio_confidence_low_max_retries", "proceeding_with_best_guess")
                logger.warning("Audio scan confidence too low after %d retries, proceeding with best guess (%.0f deg)",
                               self._audio_retries, scan_result.chosen_angle_deg)
                self._transition(SearchState.NAVIGATE, "low confidence, max retries reached")
            else:
                self._log.log_fallback("audio_confidence_low", "retry_callout")
                logger.info("Audio scan confidence low (%.3f < %.3f), retry %d/%d",
                            scan_result.confidence, self.cfg.audio_min_confidence,
                            self._audio_retries, self.cfg.max_audio_retries)
                self._transition(SearchState.CALLOUT, "low audio confidence, retrying")
        else:
            self._transition(SearchState.NAVIGATE, f"heading={scan_result.chosen_angle_deg:.0f}")

    def _run_navigate(self) -> None:
        """NAVIGATE: turn toward chosen heading and begin moving, watching for person."""
        heading = self._result.chosen_heading_deg
        logger.info("Navigating toward heading %.0f deg", heading)

        # Turn toward heading
        self._actions.turn_degrees(heading)
        time.sleep(0.2)

        # Move forward in small steps while watching for person
        t0 = time.monotonic()
        step_count = 0
        max_steps = 20  # safety cap

        while not self._stop_requested and step_count < max_steps:
            # Check for manual override
            if self._manual_found:
                self._transition(SearchState.DONE, "manual override during navigate")
                return

            frame = self._read_frame()
            if frame is not None:
                detections = self._detect_persons(frame)
                if detections:
                    best = max(detections, key=lambda d: d.score)
                    if best.score >= self.cfg.detection_threshold:
                        logger.info("Person detected during navigation! conf=%.2f", best.score)
                        self._best_frame = frame.copy()
                        self._best_confidence = best.score
                        self._last_detection_time = time.monotonic()
                        self._result.best_frame_before_approach_path = self._save_frame(
                            frame, "best_frame_before_approach"
                        )
                        self._transition(SearchState.VISION_CONFIRM, f"person detected conf={best.score:.2f}")
                        return

            # Move forward one step
            self._actions.move_forward(self.cfg.approach_step_forward_s)
            step_count += 1
            time.sleep(0.2)

            # Timeout: if navigating too long, switch to vision_confirm anyway
            if time.monotonic() - t0 > self.cfg.no_detection_rescan_s:
                break

        # No person found during navigation, try vision confirm with current view
        self._transition(SearchState.VISION_CONFIRM, "navigate timeout, trying vision")

    def _run_vision_confirm(self) -> None:
        """VISION_CONFIRM: look for person with detection, confirm visually."""
        t0 = time.monotonic()
        confirmed = False

        while not self._stop_requested and (time.monotonic() - t0) < self.cfg.vision_confirm_timeout_s:
            if self._manual_found:
                self._transition(SearchState.DONE, "manual override during vision_confirm")
                return

            frame = self._read_frame()
            if frame is None:
                time.sleep(0.1)
                continue

            detections = self._detect_persons(frame)
            if detections:
                best = max(detections, key=lambda d: d.score)
                area_frac = self._person_area_fraction(best, frame.shape)

                self._log.log_detection(
                    [{"bbox": list(d.bbox), "score": round(d.score, 3)} for d in detections],
                    best.score,
                )

                if best.score >= self.cfg.detection_threshold:
                    logger.info("Vision confirmed person: conf=%.2f area=%.3f", best.score, area_frac)
                    if best.score > self._best_confidence:
                        self._best_confidence = best.score
                        self._best_frame = frame.copy()
                    self._result.best_detection = best
                    self._result.confidence = best.score
                    self._last_detection_time = time.monotonic()

                    # Save evidence
                    if self._result.best_frame_before_approach_path is None:
                        self._result.best_frame_before_approach_path = self._save_frame(
                            frame, "best_frame_before_approach"
                        )

                    confirmed = True
                    break

            time.sleep(0.1)

        if confirmed:
            self._transition(SearchState.APPROACH, "person confirmed visually")
        else:
            # No detection: fallback to audio rescan
            self._log.log_fallback("no_visual_confirmation", "rescan_audio")
            self._audio_retries += 1
            if self._audio_retries >= self.cfg.max_audio_retries:
                self._transition(SearchState.DONE, "max retries, no person found")
            else:
                self._transition(SearchState.CALLOUT, "no visual confirm, retrying")

    def _run_approach(self) -> None:
        """APPROACH: move closer until person fills frame or depth threshold."""
        t0 = time.monotonic()
        step_count = 0
        max_steps = 50

        while not self._stop_requested and step_count < max_steps:
            if self._manual_found:
                self._transition(SearchState.DONE, "manual override during approach")
                return

            if time.monotonic() - t0 > self.cfg.approach_timeout_s:
                self._log.log_fallback("approach_timeout", "stopping")
                break

            frame = self._read_frame()
            if frame is None:
                time.sleep(0.1)
                continue

            detections = self._detect_persons(frame)
            if detections:
                best = max(detections, key=lambda d: d.score)
                area_frac = self._person_area_fraction(best, frame.shape)

                self._log.log_approach_step(area_frac, best.score)
                self._last_detection_time = time.monotonic()
                self._result.person_area_frac = area_frac
                self._result.confidence = best.score
                self._result.best_detection = best

                if best.score > self._best_confidence:
                    self._best_confidence = best.score
                    self._best_frame = frame.copy()

                # Stop conditions
                if area_frac >= self.cfg.approach_person_area_target:
                    logger.info("Person fills %.1f%% of frame — stopping approach", area_frac * 100)
                    self._result.best_frame_closeup_path = self._save_frame(frame, "best_frame_closeup")
                    self._actions.stop()
                    self._transition(SearchState.DONE, f"person area {area_frac:.2%} >= target")
                    return

                # Move forward
                self._actions.move_forward(self.cfg.approach_step_forward_s)
                step_count += 1
            else:
                # Lost detection
                elapsed_since_detect = time.monotonic() - self._last_detection_time
                if elapsed_since_detect > self.cfg.no_detection_rescan_s:
                    logger.warning("Lost person for %.1fs during approach, re-scanning", elapsed_since_detect)
                    self._log.log_fallback("lost_person_during_approach", "rescan_audio")
                    self._actions.stop()
                    self._audio_retries += 1
                    if self._audio_retries >= self.cfg.max_audio_retries:
                        self._transition(SearchState.DONE, "lost person, max retries")
                        return
                    self._transition(SearchState.CALLOUT, "lost person during approach")
                    return
                else:
                    # Brief loss: wait and retry
                    time.sleep(0.2)
                    continue

            time.sleep(0.1)

        # Approached max steps or timeout
        self._actions.stop()
        if self._best_frame is not None and self._result.best_frame_closeup_path is None:
            self._result.best_frame_closeup_path = self._save_frame(self._best_frame, "best_frame_closeup")
        self._transition(SearchState.DONE, "approach complete (max steps or timeout)")

    def _run_done(self) -> None:
        """DONE: finalize result."""
        if self._manual_found:
            self._result.found = True
            self._result.manual_override = True
            self._result.reason = "manual override"
        elif self._result.confidence >= self.cfg.detection_threshold:
            self._result.found = True
            self._result.reason = "person confirmed"
        else:
            self._result.found = False
            self._result.reason = self._result.reason or "not found"

        self._log.log_done(self._result.found, self._result.confidence, self._result.reason)
        logger.info(
            "SearchForPerson DONE: found=%s confidence=%.3f reason=%s",
            self._result.found, self._result.confidence, self._result.reason,
        )

    # ── Main run loop ────────────────────────────────────────────────

    def run(self) -> SearchResult:
        """Execute the search state machine. Blocking call.

        Returns SearchResult with found/not-found + evidence.
        """
        self._log.log("search_phase_start", {"mode": self.cfg.mode})
        logger.info("SearchForPersonPhase starting (mode=%s)", self.cfg.mode)

        handlers = {
            SearchState.CALLOUT: self._run_callout,
            SearchState.AUDIO_SCAN: self._run_audio_scan,
            SearchState.NAVIGATE: self._run_navigate,
            SearchState.VISION_CONFIRM: self._run_vision_confirm,
            SearchState.APPROACH: self._run_approach,
            SearchState.DONE: self._run_done,
        }

        while self._state != SearchState.DONE and not self._stop_requested:
            # Check manual override at any point
            if self._manual_found:
                self._transition(SearchState.DONE, "manual override")

            handler = handlers.get(self._state)
            if handler is None:
                logger.error("Unknown state: %s", self._state)
                break
            handler()

        # Ensure DONE handler runs even if we broke out
        if self._state == SearchState.DONE:
            self._run_done()

        self._log.log("search_phase_end", self._result.to_dict())
        return self._result
