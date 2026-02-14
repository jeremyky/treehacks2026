"""Mock robot implementation for dev/testing without hardware."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .robot_interface import RobotInterface

logger = logging.getLogger(__name__)


class MockRobot(RobotInterface):
    """Deterministic mock for testing. Simulates data and transitions."""

    def __init__(self, *, search_iterations_to_detect: int = 3) -> None:
        self._iteration = 0
        self._search_iterations_to_detect = search_iterations_to_detect

    def get_rgbd_frame(self) -> dict[str, Any]:
        """Return fake RGBD frame. Person 'detected' after N iterations."""
        self._iteration += 1
        person_in_frame = self._iteration >= self._search_iterations_to_detect
        return {
            "rgb": b"fake_rgb_data",
            "depth": b"fake_depth_data",
            "width": 640,
            "height": 480,
            "person_detected": person_in_frame,
            "iteration": self._iteration,
        }

    def get_imu(self) -> dict[str, float]:
        """Return fake IMU."""
        return {"ax": 0.0, "ay": 0.0, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.0}

    def play_tts(self, text: str) -> None:
        """Log instead of speaking."""
        logger.info("TTS: %s", text)

    def listen_asr(self, timeout_s: float) -> str | None:
        """Mock ASR: return None (no speech heard) for determinism."""
        logger.debug("ASR listen (timeout=%.1fs) -> None", timeout_s)
        return None

    def set_velocity(self, vx: float, wz: float) -> None:
        """Log velocity command."""
        logger.debug("set_velocity(vx=%.2f, wz=%.2f)", vx, wz)

    def stop(self) -> None:
        """Log stop."""
        logger.debug("stop()")
