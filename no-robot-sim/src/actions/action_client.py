"""
ActionClient: clean interface for navigation, speak, clear_debris, scan_injuries, send_report.
Teammates replace the placeholder implementation with real hardware calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import ActionResult


class ActionClient(ABC):
    """
    Action layer interface. All methods return ActionResult.
    Implement in placeholders.py (WoZ) or a real client for robot/motors/speaker.
    """

    @abstractmethod
    def navigate_to(self, target_pose: dict[str, Any], reason: str = "") -> ActionResult:
        """Navigate to target (x, y, yaw or similar)."""
        ...

    @abstractmethod
    def explore_step(self, reason: str = "") -> ActionResult:
        """Perform one exploration step (e.g. rotate or move forward)."""
        ...

    @abstractmethod
    def stop(self, reason: str = "") -> ActionResult:
        """Stop all motion."""
        ...

    @abstractmethod
    def speak(self, text: str, reason: str = "") -> ActionResult:
        """Speak text (TTS or play clip)."""
        ...

    @abstractmethod
    def clear_debris(self, strategy: str, reason: str = "") -> ActionResult:
        """Attempt to clear debris (e.g. push, lift). strategy: 'push' | 'lift' | 'mark_only'."""
        ...

    @abstractmethod
    def scan_injuries(self, reason: str = "") -> ActionResult:
        """Perform injury scan (e.g. capture viewpoints, run classifier)."""
        ...

    @abstractmethod
    def send_report(self, report: dict[str, Any], reason: str = "") -> ActionResult:
        """Send report to command center / save to disk."""
        ...
