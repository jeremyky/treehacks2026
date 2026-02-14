"""Lightweight JSONL event logger for search phase timeline.

Each event is one JSON dict per line. Designed for later "command center" reporting.
Logs: timestamps, state transitions, audio scan results, detections, headings, frames saved.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SearchEventLogger:
    """Append-only JSONL logger for the SearchForPerson phase.

    Usage:
        log = SearchEventLogger("logs/search_events.jsonl")
        log.log("state_transition", {"from": "CALLOUT", "to": "AUDIO_SCAN"})
        log.log("audio_sample", {"angle_deg": 30, "rms": 0.05})
    """

    def __init__(self, path: str | Path = "logs/search_events.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._session_id = f"search_{int(time.time())}"
        logger.info("SearchEventLogger: writing to %s (session=%s)", self._path, self._session_id)

    @property
    def path(self) -> Path:
        return self._path

    def log(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Append one event line to the JSONL file."""
        entry: dict[str, Any] = {
            "timestamp": time.time(),
            "timestamp_mono": time.monotonic(),
            "session": self._session_id,
            "event": event_type,
        }
        if data:
            entry.update(data)
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning("SearchEventLogger write failed: %s", e)

    def log_state_transition(self, from_state: str, to_state: str, reason: str = "") -> None:
        self.log("state_transition", {"from_state": from_state, "to_state": to_state, "reason": reason})

    def log_audio_scan_start(self, n_steps: int, step_deg: float) -> None:
        self.log("audio_scan_start", {"n_steps": n_steps, "step_deg": step_deg})

    def log_audio_sample(self, sample_dict: dict) -> None:
        self.log("audio_sample", sample_dict)

    def log_audio_scan_result(self, result_dict: dict) -> None:
        self.log("audio_scan_result", result_dict)

    def log_detection(self, detections: list[dict], confidence: float, frame_path: str | None = None) -> None:
        self.log("vision_detection", {
            "num_persons": len(detections),
            "confidence": round(confidence, 3),
            "frame_path": frame_path,
            "detections": detections[:5],  # cap for log size
        })

    def log_approach_step(self, person_area_frac: float, confidence: float, distance_m: float | None = None) -> None:
        self.log("approach_step", {
            "person_area_frac": round(person_area_frac, 4),
            "confidence": round(confidence, 3),
            "distance_m": distance_m,
        })

    def log_frame_saved(self, label: str, path: str) -> None:
        self.log("frame_saved", {"label": label, "path": path})

    def log_fallback(self, reason: str, action: str) -> None:
        self.log("fallback", {"reason": reason, "action": action})

    def log_manual_override(self, key: str) -> None:
        self.log("manual_override", {"key": key})

    def log_done(self, found: bool, confidence: float, reason: str = "") -> None:
        self.log("search_done", {"found": found, "confidence": round(confidence, 3), "reason": reason})
