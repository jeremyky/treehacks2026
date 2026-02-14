"""Frame storage: latest in-memory + ring buffer with JPEG compression."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .types import Observation


@dataclass
class RingBufferEntry:
    """Single ring buffer slot: timestamp, compressed frame, observation summary."""

    timestamp: float
    jpeg_bytes: bytes
    observation_summary: Observation | None


class LatestFrameStore:
    """Thread-safe store for latest frame (BGR) and latest Observation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame_bgr: np.ndarray | None = None
        self._observation: Observation | None = None

    def update(self, frame: np.ndarray, obs: Observation) -> None:
        with self._lock:
            self._frame_bgr = frame.copy() if frame is not None else None
            self._observation = obs

    def get_latest(self) -> tuple[np.ndarray | None, Observation | None]:
        with self._lock:
            return (
                self._frame_bgr.copy() if self._frame_bgr is not None else None,
                self._observation,
            )


class RingBuffer:
    """Ring buffer of (timestamp, jpeg_bytes, observation_summary) at fixed sample rate."""

    def __init__(
        self,
        max_seconds: float,
        fps_sample: float,
        jpeg_quality: int = 85,
    ) -> None:
        self._max_seconds = max_seconds
        self._fps_sample = fps_sample
        self._jpeg_quality = jpeg_quality
        self._min_interval = 1.0 / fps_sample if fps_sample > 0 else 1.0
        self._entries: list[RingBufferEntry] = []
        self._last_push_time: float = 0.0
        self._lock = threading.Lock()

    def push(self, frame_bgr: np.ndarray, obs: Observation | None) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_push_time < self._min_interval:
                return
            self._last_push_time = now
            _, jpeg = cv2.imencode(
                ".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
            )
            jpeg_bytes = jpeg.tobytes()
            entry = RingBufferEntry(timestamp=now, jpeg_bytes=jpeg_bytes, observation_summary=obs)
            self._entries.append(entry)
            cutoff = now - self._max_seconds
            while self._entries and self._entries[0].timestamp < cutoff:
                self._entries.pop(0)

    def get_window(self, seconds_back: float) -> list[RingBufferEntry]:
        """Return entries from the last seconds_back seconds."""
        with self._lock:
            cutoff = time.monotonic() - seconds_back
            return [e for e in self._entries if e.timestamp >= cutoff]

    def get_keyframes(
        self,
        k: int = 3,
        seconds_back: float | None = None,
        strategy: str = "spread",
    ) -> list[RingBufferEntry]:
        """Return k frames spread across the last window. strategy: 'spread'."""
        window_sec = seconds_back if seconds_back is not None else self._max_seconds
        entries = self.get_window(window_sec)
        if not entries or k <= 0:
            return []
        if len(entries) <= k:
            return list(entries)
        if strategy == "spread":
            step = (len(entries) - 1) / max(k - 1, 1)
            indices = [int(round(i * step)) for i in range(k)]
            return [entries[i] for i in indices]
        return entries[-k:]
