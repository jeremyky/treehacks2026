"""
Deterministic triage script: ordered prompts for rescue-medic dialogue.
No LLM required. Used by ASSIST_COMMUNICATE policy.

This file is a preserved copy ("v2") to avoid losing the script during demo iteration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TriageStep:
    key: str
    question: str
    expected_answer_type: str  # "yesno" | "free_text" | "scale_0_10"
    followups: dict[str, Any] | None = None  # e.g. {"if_yes": "Where exactly?"}


# Step 0: initial (handled in policy: "Are you hurt? Do you need help?")
# Step 1: acknowledge (SAY only, no ASK)
# Steps 2..N: triage questions
TRIAGE_ACKNOWLEDGE_SAY = "Noted. Sending to command center."

TRIAGE_STEPS: list[TriageStep | str] = [
    # Step 0: index 0 = initial ask (policy uses this when no last_response yet)
    TriageStep("initial", "Are you hurt? Do you need help?", "free_text"),
    # Step 1: acknowledge (SAY) - no TriageStep, policy emits TRIAGE_ACKNOWLEDGE_SAY
    "acknowledge",  # sentinel: policy says TRIAGE_ACKNOWLEDGE_SAY
    # MARCH triage order (deterministic, short for TTS)
    # M — Massive hemorrhage
    TriageStep("massive_bleeding", "Is there heavy bleeding right now?", "yesno"),
    TriageStep("massive_bleeding_where", "Where is the bleeding?", "free_text"),
    # A — Airway
    TriageStep("airway_talking", "Can you talk to me clearly?", "yesno"),
    # R — Respiration
    TriageStep("breathing_trouble", "Are you having trouble breathing?", "yesno"),
    TriageStep("chest_injury", "Any chest injury or a hole in the chest?", "yesno"),
    # C — Circulation / shock
    TriageStep("shock_signs", "Do you feel dizzy, faint, or very cold and clammy?", "yesno"),
    TriageStep("small_bleeds", "Any other bleeding or wounds I should know about?", "free_text"),
    # H — Hypothermia / Head injury
    TriageStep("head_injury", "Did you hit your head or black out?", "yesno"),
    TriageStep("keep_warm", "Are you feeling very cold right now?", "yesno"),
    # Documentation / handoff helpers (keep later, after life threats)
    TriageStep("pain", "Where does it hurt most? Rate your pain from 0 to 10.", "free_text"),
    TriageStep("mobility", "Can you move your arms and legs? Are you trapped or pinned?", "free_text"),
    TriageStep("consent_photos", "Is it okay if I take photos to help medics triage you?", "yesno"),
]


def get_step(index: int) -> TriageStep | str | None:
    """Return triage step at index, or None if past end."""
    if index < 0 or index >= len(TRIAGE_STEPS):
        return None
    return TRIAGE_STEPS[index]


def is_acknowledge_step(index: int) -> bool:
    """Step 1 is SAY-only acknowledge."""
    return index == 1 and len(TRIAGE_STEPS) > 1 and TRIAGE_STEPS[1] == "acknowledge"


def num_steps() -> int:
    return len(TRIAGE_STEPS)


def step_after_acknowledge() -> int:
    """First real triage Q index after acknowledge."""
    return 2

