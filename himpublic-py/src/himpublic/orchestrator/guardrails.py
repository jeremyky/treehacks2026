"""
Guardrails for LLM-proposed actions: validate action enum, clamp time bounds,
reject unknown phase transitions. Returns sanitized dict or None if invalid.
"""

from __future__ import annotations

from typing import Any

from himpublic.orchestrator.llm_adapter import ALLOWED_ACTIONS
from himpublic.orchestrator.phases import Phase

# Bounds for wait_for_response_s (seconds) — allow longer so victim has time to respond
WAIT_FOR_RESPONSE_MIN = 0.0
WAIT_FOR_RESPONSE_MAX = 25.0

KNOWN_PHASES = frozenset(p.value for p in Phase)


def validate_llm_proposal(proposal: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Validate and sanitize LLM proposal. Returns a dict safe to use for Decision
    construction, or None if invalid.

    - action must be in ALLOWED_ACTIONS
    - wait_for_response_s clamped to [0, 25]; set to None if missing or invalid
    - next_phase must be in KNOWN_PHASES (reject unknown)
    - confidence retained as-is (caller may threshold)
    """
    if proposal is None or not isinstance(proposal, dict):
        return None

    action = proposal.get("action")
    if action is None:
        return None
    action_str = str(action).strip().lower()
    if action_str not in ALLOWED_ACTIONS:
        return None

    out: dict[str, Any] = {
        "action": action_str,
        "confidence": float(proposal.get("confidence", 0.0)),
    }

    # Optional say
    say = proposal.get("say")
    if say is not None and isinstance(say, str) and say.strip():
        out["say"] = say.strip()[:500]  # cap length
    else:
        out["say"] = None

    # Clamp wait_for_response_s to safe bounds
    wait = proposal.get("wait_for_response_s")
    if wait is not None:
        try:
            w = float(wait)
            if WAIT_FOR_RESPONSE_MIN <= w <= WAIT_FOR_RESPONSE_MAX:
                out["wait_for_response_s"] = w
            else:
                out["wait_for_response_s"] = max(WAIT_FOR_RESPONSE_MIN, min(WAIT_FOR_RESPONSE_MAX, w))
        except (TypeError, ValueError):
            out["wait_for_response_s"] = None
    else:
        out["wait_for_response_s"] = None

    # Reject unknown phase transitions
    next_phase = proposal.get("next_phase")
    if next_phase is not None and isinstance(next_phase, str):
        np = next_phase.strip().lower()
        if np in KNOWN_PHASES:
            out["next_phase"] = np
        else:
            out["next_phase"] = None  # invalid phase, do not transition
    else:
        out["next_phase"] = None

    return out
