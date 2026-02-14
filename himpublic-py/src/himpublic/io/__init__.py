"""I/O module - robot interface and adapters."""

from .robot_interface import RobotInterface
from .mock_robot import MockRobot

__all__ = ["RobotInterface", "MockRobot"]
