"""Abstract robot interface - Protocol for swappable adapters."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RobotInterface(Protocol):
    """Abstract interface for robot I/O. Implementations: MockRobot, BoosterAdapter, Ros2Bridge."""

    def get_rgbd_frame(self) -> dict[str, Any]:
        """Return RGB + depth frame. Mock returns fake data."""
        ...

    def get_imu(self) -> dict[str, float]:
        """Return IMU readings (accel, gyro, etc.)."""
        ...

    def play_tts(self, text: str) -> None:
        """Play text-to-speech."""
        ...

    def listen_asr(self, timeout_s: float) -> str | None:
        """Listen for speech, return transcript or None on timeout."""
        ...

    def set_velocity(self, vx: float, wz: float) -> None:
        """Set linear (vx) and angular (wz) velocity."""
        ...

    def stop(self) -> None:
        """Stop all motion."""
        ...
