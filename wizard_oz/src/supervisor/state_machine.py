"""
State machine: SEARCH -> APPROACH -> DEBRIS -> INJURY -> REPORT.
Uses ActionClient (placeholder) and perception detectors (key toggles).
Robust: timeouts, fallback to SEARCH if detection lost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .phases import Phase, next_phase
from ..actions import ActionClient
from ..perception import detect_humans, detect_debris, detect_injuries
from ..perception.types import Detection, DebrisFinding, InjuryFinding


@dataclass
class RunContext:
    """Shared context across phases."""
    target_pose: dict[str, Any] = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "yaw": 0.0})
    phase_entered_at: float = 0.0
    phase_log: list[dict[str, Any]] = field(default_factory=list)
    last_humans: list[Detection] = field(default_factory=list)
    last_debris: list[DebrisFinding] = field(default_factory=list)
    last_injuries: list[InjuryFinding] = field(default_factory=list)
    last_action_name: str = ""
    last_action_reason: str = ""
    step_count: int = 0
    callout_last_at: float = 0.0


class StateMachine:
    """
    Wizard-of-Oz state machine. Runs one tick per call; main loop calls tick() at ~10Hz.
    """

    def __init__(
        self,
        action_client: ActionClient,
        phase_timeout_s: float = 120.0,
        callout_interval_s: float = 5.0,
        max_steps: int = 0,
    ) -> None:
        self.action = action_client
        self.phase_timeout_s = phase_timeout_s
        self.callout_interval_s = callout_interval_s
        self.max_steps = max_steps
        self.phase = Phase.SEARCH
        self.ctx = RunContext()
        self.ctx.phase_entered_at = time.monotonic()
        self._approach_done = False
        self._debris_done = False
        self._injury_done = False

    def tick(
        self,
        frame: Any,
        current_time: float | None = None,
    ) -> bool:
        """
        One tick: run perception, phase logic, actions. Returns False when DONE or max_steps.
        """
        t = current_time if current_time is not None else time.monotonic()
        self.ctx.step_count += 1
        if self.max_steps > 0 and self.ctx.step_count >= self.max_steps:
            return False

        if self.phase == Phase.DONE:
            return False

        # Perception (use placeholders; toggles set by keys in main)
        self.ctx.last_humans = detect_humans(frame)
        self.ctx.last_debris = detect_debris(frame)
        self.ctx.last_injuries = detect_injuries(frame)

        # Timeout: fall back to SEARCH
        if t - self.ctx.phase_entered_at > self.phase_timeout_s:
            self._transition_to(Phase.SEARCH, t, "timeout")

        if self.phase == Phase.SEARCH:
            self._tick_search(t)
        elif self.phase == Phase.APPROACH:
            self._tick_approach(t)
        elif self.phase == Phase.DEBRIS_ASSESS:
            self._tick_debris(t)
        elif self.phase == Phase.INJURY_SCAN:
            self._tick_injury(t)
        elif self.phase == Phase.REPORT:
            self._tick_report(t)

        return self.phase != Phase.DONE

    def _transition_to(self, new_phase: Phase, t: float, reason: str = "") -> None:
        self.ctx.phase_log.append({
            "phase": self.phase.value,
            "next": new_phase.value,
            "reason": reason,
            "t": t,
        })
        self.phase = new_phase
        self.ctx.phase_entered_at = t

    def _tick_search(self, t: float) -> None:
        # Call out every N seconds
        if t - self.ctx.callout_last_at >= self.callout_interval_s:
            self.action.speak("Calling out... Can you respond?", reason="search_callout")
            self.ctx.callout_last_at = t
            self.ctx.last_action_name = "speak"
            self.ctx.last_action_reason = "search_callout"
        # Human detected -> set target and go to APPROACH
        if self.ctx.last_humans:
            d = self.ctx.last_humans[0]
            self.ctx.target_pose = {
                "x": 1.5,
                "y": 0.0,
                "yaw": d.bearing_rad or 0.0,
            }
            self._transition_to(Phase.APPROACH, t, "human_detected")

    def _tick_approach(self, t: float) -> None:
        if not self._approach_done:
            self.action.navigate_to(self.ctx.target_pose, reason="approach_target")
            self.ctx.last_action_name = "navigate_to"
            self.ctx.last_action_reason = "approach_target"
            self._approach_done = True
            return
        # Re-confirm human (or key 'h') then go to DEBRIS
        if self.ctx.last_humans or self._approach_done:
            self._transition_to(Phase.DEBRIS_ASSESS, t, "approach_done")
            self._debris_done = False

    def _tick_debris(self, t: float) -> None:
        if not self._debris_done:
            if self.ctx.last_debris:
                self.action.clear_debris("push", reason="debris_near_target")
                self.ctx.last_action_name = "clear_debris"
                self.ctx.last_action_reason = "debris_near_target"
            self._debris_done = True
            return
        # One tick after done, advance to INJURY
        self._transition_to(Phase.INJURY_SCAN, t, "debris_done")
        self._injury_done = False

    def _tick_injury(self, t: float) -> None:
        if not self._injury_done:
            self.action.scan_injuries(reason="injury_scan")
            self.ctx.last_action_name = "scan_injuries"
            self.ctx.last_action_reason = "injury_scan"
            self._injury_done = True
            return
        # One tick after done, advance to REPORT
        self._transition_to(Phase.REPORT, t, "injury_scan_done")

    def _tick_report(self, t: float) -> None:
        report = self.build_report(t)
        self.action.send_report(report, reason="final_report")
        self.ctx.last_action_name = "send_report"
        self.ctx.last_action_reason = "final_report"
        self._transition_to(Phase.DONE, t, "report_sent")

    def build_report(self, t: float) -> dict[str, Any]:
        """Build report JSON: timestamps, phase log, findings, snapshot placeholder."""
        return {
            "timestamp": t,
            "phase_log": list(self.ctx.phase_log),
            "last_humans": [
                {"confidence": d.confidence, "bearing_rad": d.bearing_rad, "distance_m": d.distance_m}
                for d in self.ctx.last_humans
            ],
            "last_debris": [
                {"confidence": d.confidence, "movable": d.movable, "description": d.description}
                for d in self.ctx.last_debris
            ],
            "last_injuries": [
                {"label": i.label, "body_region": i.body_region, "severity_estimate": i.severity_estimate, "confidence": i.confidence}
                for i in self.ctx.last_injuries
            ],
            "snapshot_path": "artifacts/reports/snapshot.jpg",
        }

    def force_next_phase(self, t: float) -> None:
        """Demo key 'n': force advance to next phase."""
        n = next_phase(self.phase)
        if n is not None:
            self._transition_to(n, t, "manual_next")
            if n == Phase.APPROACH:
                self._approach_done = False
            elif n == Phase.DEBRIS_ASSESS:
                self._debris_done = False
            elif n == Phase.INJURY_SCAN:
                self._injury_done = False
