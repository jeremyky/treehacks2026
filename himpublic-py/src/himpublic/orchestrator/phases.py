"""High-level mission phases. Each phase has clear exit conditions so you can demo or fail independently."""

from __future__ import annotations

from enum import Enum
from typing import Any


class Phase(Enum):
    """
    Mission phases. Exit conditions and behaviors are documented so each phase
    can be demoed independently and failures are contained.
    """

    # Verify sensors (RGB-D, IMU, mic), localization, comms. Exit: "ready" or "degraded" (e.g. no depth).
    BOOT = "boot"

    # Patrol, explore, scan, call out ("Can you respond?"), listen. Output: candidate detections + position.
    # Exit: confidence above threshold OR time limit → fallback (expand search / ask operator).
    SEARCH_LOCALIZE = "search_localize"

    # Navigate to candidate, re-detect, confirm person (not mannequin/poster). Optional yes/no ("Are you injured?").
    # Exit: confirmed + safe standoff established.
    APPROACH_CONFIRM = "approach_confirm"

    # Quick scan for hazards (rubble, drop-offs). Choose camera viewpoints for injury scan.
    # Exit: "safe enough" or "needs human responder".
    SCENE_SAFETY_TRIAGE = "scene_safety_triage"

    # Rubble assessment: detect blocking, movable vs not, push/clear if feasible else report with images.
    # Exit: access improved OR "not movable".
    DEBRIS_ASSESSMENT = "debris_assessment"

    # Injury classifier (bleeding, burns, fractures, unconsciousness). Structured report + images.
    # Exit: report complete OR sensor confidence too low (request better viewpoint).
    INJURY_DETECTION = "injury_detection"

    # Talk to victim (dialogue + triage questions). Exit: triage complete → SCAN_CAPTURE.
    ASSIST_COMMUNICATE = "assist_communicate"

    # Take photos / "scan body" placeholder. Exit: images captured → REPORT_SEND.
    SCAN_CAPTURE = "scan_capture"

    # Compile structured report and send to command center. Exit: sent → HANDOFF_ESCORT.
    REPORT_SEND = "report_send"

    # Multi-victim: mark this one, continue. Or escort to safe point. Exit: mission command.
    HANDOFF_ESCORT = "handoff_escort"

    # Legacy / terminal
    DONE = "done"


# Human-readable labels and short behavior hints for telemetry/UI
PHASE_LABELS: dict[Phase, str] = {
    Phase.BOOT: "Boot / Self-check",
    Phase.SEARCH_LOCALIZE: "Search & Localize Rubble",
    Phase.APPROACH_CONFIRM: "Approach & Confirm Rubble",
    Phase.SCENE_SAFETY_TRIAGE: "Scene Safety & Triage Setup",
    Phase.DEBRIS_ASSESSMENT: "Debris Assessment & Removal",
    Phase.INJURY_DETECTION: "Injury Detection & Documentation",
    Phase.ASSIST_COMMUNICATE: "Communicate & Report Status",
    Phase.SCAN_CAPTURE: "Scan & Capture Images",
    Phase.REPORT_SEND: "Send Report to Command Center",
    Phase.HANDOFF_ESCORT: "Handoff / Continue Search",
    Phase.DONE: "Done",
}

# Short spoken announcements when entering each phase (robot states out loud)
PHASE_ANNOUNCE: dict[Phase, str] = {
    Phase.BOOT: "Booting up. Running self-check.",
    Phase.SEARCH_LOCALIZE: "Scanning area for rubble and debris.",
    Phase.APPROACH_CONFIRM: "I see something ahead. Moving closer to confirm.",
    Phase.SCENE_SAFETY_TRIAGE: "Checking scene safety.",
    Phase.DEBRIS_ASSESSMENT: "I found rubble. Assessing the debris now.",
    Phase.INJURY_DETECTION: "Documenting the scene.",
    Phase.ASSIST_COMMUNICATE: "Reporting what I found. I will describe the situation.",
    Phase.SCAN_CAPTURE: "Capturing images of the debris for the team.",
    Phase.REPORT_SEND: "Sending report to command center.",
    Phase.HANDOFF_ESCORT: "Report sent. Standing by for next task.",
    Phase.DONE: "Mission complete. Standing by.",
}

# Exit condition labels (for logging / operator)
PHASE_EXIT_NOTES: dict[Phase, str] = {
    Phase.BOOT: "ready | degraded (e.g. no depth)",
    Phase.SEARCH_LOCALIZE: "confidence above threshold | time limit → fallback",
    Phase.APPROACH_CONFIRM: "confirmed + safe standoff",
    Phase.SCENE_SAFETY_TRIAGE: "safe enough | needs human responder",
    Phase.DEBRIS_ASSESSMENT: "access improved | not movable",
    Phase.INJURY_DETECTION: "report complete | low confidence",
    Phase.ASSIST_COMMUNICATE: "triage complete → scan",
    Phase.SCAN_CAPTURE: "images captured → report",
    Phase.REPORT_SEND: "report sent → handoff",
    Phase.HANDOFF_ESCORT: "mission command",
    Phase.DONE: "—",
}


def phase_to_legacy_mode(phase: Phase) -> str:
    """Map Phase to legacy mode string (SEARCH, APPROACH, ASSESS, REPORT) for policy/observation."""
    if phase in (Phase.BOOT, Phase.SEARCH_LOCALIZE):
        return "SEARCH"
    if phase == Phase.APPROACH_CONFIRM:
        return "APPROACH"
    if phase in (Phase.SCENE_SAFETY_TRIAGE, Phase.DEBRIS_ASSESSMENT, Phase.INJURY_DETECTION):
        return "ASSESS"
    if phase in (Phase.ASSIST_COMMUNICATE, Phase.SCAN_CAPTURE, Phase.REPORT_SEND, Phase.HANDOFF_ESCORT, Phase.DONE):
        return "REPORT"
    return "SEARCH"


def parse_phase(value: str | Phase) -> Phase:
    """Parse string (e.g. from config) to Phase. Default SEARCH_LOCALIZE."""
    if isinstance(value, Phase):
        return value
    s = (value or "").strip().lower()
    for p in Phase:
        if p.value == s or p.value.replace("_", "") == s.replace("-", ""):
            return p
    return Phase.SEARCH_LOCALIZE
