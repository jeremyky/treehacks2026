"""Booster SDK adapter. Skeleton for real robot integration."""

from __future__ import annotations

import logging
from typing import Any

from .robot_interface import RobotInterface

logger = logging.getLogger(__name__)


class BoosterAdapter(RobotInterface):
    """Bridge to Booster SDK. Real SDK calls will be inserted per TODO comments below."""

    def __init__(
        self,
        robot_ip: str = "192.168.1.100",
        username: str = "admin",
        password: str | None = None,
        ssh_key_path: str | None = None,
    ) -> None:
        """
        Initialize adapter. No real connection yet.

        Args:
            robot_ip: Robot IP address (placeholder default)
            username: SSH/API username
            password: Optional password (prefer ssh_key_path for auth)
            ssh_key_path: Optional path to SSH private key for auth
        """
        self.robot_ip = robot_ip
        self.username = username
        self._password = password
        self._ssh_key_path = ssh_key_path
        logger.info(
            "BoosterAdapter: connection attempt (placeholder) robot_ip=%s username=%s "
            "auth=%s",
            robot_ip,
            username,
            "ssh_key" if ssh_key_path else "password" if password else "none",
        )
        # TODO: Insert Booster SDK connection here (e.g., init network channel)

    def get_rgbd_frame(self) -> dict[str, Any]:
        """Return RGB + depth frame from robot camera."""
        logger.debug("BoosterAdapter.get_rgbd_frame() called")
        # TODO: Insert Booster SDK camera subscriber or get_frame() call
        raise NotImplementedError(
            "BoosterAdapter.get_rgbd_frame: Booster SDK camera call not yet inserted"
        )

    def get_imu(self) -> dict[str, float]:
        """Return IMU readings (accel, gyro, etc.)."""
        logger.debug("BoosterAdapter.get_imu() called")
        # TODO: Insert Booster SDK IMU subscriber or get_imu() call
        raise NotImplementedError(
            "BoosterAdapter.get_imu: Booster SDK IMU call not yet inserted"
        )

    def play_tts(self, text: str) -> None:
        """Play text-to-speech on robot speakers."""
        logger.info("BoosterAdapter.play_tts(%r)", text)
        # TODO: Insert Booster SDK TTS service call or audio playback
        raise NotImplementedError(
            "BoosterAdapter.play_tts: Booster SDK TTS call not yet inserted"
        )

    def listen_asr(self, timeout_s: float) -> str | None:
        """Listen for speech, return transcript or None on timeout."""
        logger.debug("BoosterAdapter.listen_asr(timeout_s=%s)", timeout_s)
        # TODO: Insert Booster SDK ASR/microphone capture call
        raise NotImplementedError(
            "BoosterAdapter.listen_asr: Booster SDK ASR call not yet inserted"
        )

    def set_velocity(self, vx: float, wz: float) -> None:
        """Set linear (vx) and angular (wz) velocity."""
        logger.info("BoosterAdapter.set_velocity(vx=%s, wz=%s)", vx, wz)
        # TODO: Insert Booster SDK base velocity publisher or command
        raise NotImplementedError(
            "BoosterAdapter.set_velocity: Booster SDK velocity command not yet inserted"
        )

    def stop(self) -> None:
        """Stop all motion."""
        logger.info("BoosterAdapter.stop()")
        # TODO: Insert Booster SDK stop/emergency stop call
        raise NotImplementedError(
            "BoosterAdapter.stop: Booster SDK stop call not yet inserted"
        )
