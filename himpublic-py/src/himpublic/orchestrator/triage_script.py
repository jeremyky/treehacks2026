"""
Deterministic triage script: ordered prompts for rescue-medic dialogue.
No LLM required. Used by ASSIST_COMMUNICATE policy.
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
    TriageStep("consent_photos", "Is it okay if I take photos to help medics triage you?", "yesno"),
    TriageStep("immediate_danger", "Do you see or smell fire, smoke, water, or unstable debris nearby?", "yesno"),
    TriageStep("breathing_difficulty", "Are you having any trouble breathing?", "yesno"),
    TriageStep("bleeding", "Are you bleeding heavily? If yes, where?", "free_text"),  # followup: where
    TriageStep("pain", "Where does it hurt most? Rate your pain from 0 to 10.", "free_text"),  # parse 0-10
    TriageStep("mobility", "Can you move your arms and legs? Are you trapped or pinned?", "free_text"),
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
