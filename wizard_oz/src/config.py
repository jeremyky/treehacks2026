"""Wizard-of-Oz runtime config. Set via CLI or env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return default


@dataclass
class Config:
    """Runtime configuration. Teammates can override for real hardware."""

    manual_confirm_actions: bool = False  # Wait for Enter after each action
    typed_mic: bool = False  # Type transcript instead of real mic
    show: bool = True  # Show webcam window
    save_video: bool = False  # Save frames to video file
    save_video_path: str = "artifacts/video.avi"
    loop_hz: float = 10.0
    callout_interval_s: float = 5.0
    phase_timeout_s: float = 120.0
    max_steps: int = 0  # 0 = no limit
    artifacts_dir: str = "artifacts"
    reports_dir: str = "artifacts/reports"

    # Key toggles (set by main loop when user presses keys)
    toggle_human: bool = field(default=False, repr=False)
    toggle_debris: bool = field(default=False, repr=False)
    toggle_injury: bool = field(default=False, repr=False)

    @classmethod
    def from_args(cls, args) -> "Config":
        c = cls(
            manual_confirm_actions=getattr(args, "manual", False),
            typed_mic=getattr(args, "typed_mic", False),
            show=getattr(args, "show", True),
            save_video=getattr(args, "save_video", False),
            save_video_path=getattr(args, "save_video_path", "artifacts/video.avi") or "artifacts/video.avi",
            loop_hz=10.0,
            callout_interval_s=5.0,
            phase_timeout_s=120.0,
            max_steps=getattr(args, "max_steps", 0) or 0,
        )
        return c


# Global for action placeholders (set by main)
MANUAL_CONFIRM_ACTIONS: bool = False
