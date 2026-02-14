"""Placeholder optional ROS2 adapter. TODO: implement only if forced by robot SDK."""

from __future__ import annotations

import logging
from typing import Any

from .robot_interface import RobotInterface

logger = logging.getLogger(__name__)


class Ros2Bridge(RobotInterface):
    """TODO: Optional ROS2 bridge. Use only if robot SDK requires ROS2 for I/O."""

    def get_rgbd_frame(self) -> dict[str, Any]:
        raise NotImplementedError("Ros2Bridge not implemented - use MockRobot for now")

    def get_imu(self) -> dict[str, float]:
        raise NotImplementedError("Ros2Bridge not implemented - use MockRobot for now")

    def play_tts(self, text: str) -> None:
        raise NotImplementedError("Ros2Bridge not implemented - use MockRobot for now")

    def listen_asr(self, timeout_s: float) -> str | None:
        raise NotImplementedError("Ros2Bridge not implemented - use MockRobot for now")

    def set_velocity(self, vx: float, wz: float) -> None:
        raise NotImplementedError("Ros2Bridge not implemented - use MockRobot for now")

    def stop(self) -> None:
        raise NotImplementedError("Ros2Bridge not implemented - use MockRobot for now")
