"""Two-layer brain: ReflexController (fast) + LLMPolicy (slow). Phase-based transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from himpublic.perception.types import Observation
from himpublic.orchestrator.phases import Phase
from himpublic.orchestrator.guardrails import validate_llm_proposal
from himpublic.orchestrator.triage_script import (
    TRIAGE_ACKNOWLEDGE_SAY,
    TRIAGE_STEPS,
    get_step,
    is_acknowledge_step,
    num_steps,
    TriageStep,
)
from himpublic.orchestrator.triage_parse import parse_yesno, parse_for_step, parse_pain_score


class Action(Enum):
    STOP = "stop"
    ROTATE_LEFT = "rotate_left"
    ROTATE_RIGHT = "rotate_right"
    FORWARD_SLOW = "forward_slow"
    BACK_UP = "back_up"
    WAIT = "wait"
    ASK = "ask"
    SAY = "say"


@dataclass
class Decision:
    action: Action
    params: dict[str, Any]
    say: str | None
    wait_for_response_s: float | None
    mode: str  # phase value (e.g. search_localize, approach_confirm)
    confidence: float
    used_llm: bool = False  # True when this decision came from LLM proposal (after guardrails)


# Safe thresholds for reflex layer
OBSTACLE_SAFE_M = 0.5
CENTER_OFFSET_THRESHOLD = 0.2  # turn if |primary_person_center_offset| > this


class ReflexController:
    """Fast, deterministic safety layer. Override to STOP or turn toward person."""

    def __init__(
        self,
        obstacle_safe_m: float = OBSTACLE_SAFE_M,
        center_threshold: float = CENTER_OFFSET_THRESHOLD,
    ) -> None:
        self._obstacle_safe_m = obstacle_safe_m
        self._center_threshold = center_threshold

    def override(self, obs: Observation | None) -> Action | None:
        """
        Return low-level override action or None if policy action is safe.
        - STOP if obstacle too close.
        - ROTATE_LEFT / ROTATE_RIGHT to center person if detected and offset large.
        """
        if obs is None:
            return None
        if obs.obstacle_distance_m is not None and obs.obstacle_distance_m < self._obstacle_safe_m:
            return Action.STOP
        if obs.persons and abs(obs.primary_person_center_offset) > self._center_threshold:
            return Action.ROTATE_LEFT if obs.primary_person_center_offset > 0 else Action.ROTATE_RIGHT
        return None


def _current_phase(conv: dict[str, Any]) -> str:
    return conv.get("phase") or conv.get("mode") or Phase.SEARCH_LOCALIZE.value


def _action_from_string(s: str) -> Action:
    """Map validated action string to Action enum. Default WAIT for unknown."""
    try:
        return Action(s.strip().lower())
    except ValueError:
        return Action.WAIT


def _decision_from_llm_proposal(validated: dict[str, Any], current_phase: str) -> Decision:
    """Build Decision from guardrails-validated LLM proposal."""
    action = _action_from_string(validated["action"])
    next_phase = validated.get("next_phase") or current_phase
    return Decision(
        action=action,
        params={},
        say=validated.get("say"),
        wait_for_response_s=validated.get("wait_for_response_s"),
        mode=next_phase,
        confidence=float(validated.get("confidence", 0.5)),
        used_llm=True,
    )


class LLMPolicy:
    """
    High-level policy (1–2 Hz). Phase-based: each phase has clear exit conditions.
    Stub: rules-based. Swap to real LLM by replacing decide() body.
    """

    def decide(
        self,
        obs: Observation | None,
        conversation_state: dict[str, Any],
        llm_proposal: dict[str, Any] | None = None,
    ) -> Decision:
        """
        Return Decision. mode = next phase value. FSM is always the fallback.
        When llm_proposal is provided and valid (after guardrails), use it for
        SEARCH_LOCALIZE (if confidence >= 0.6) and ASSIST_COMMUNICATE; else use FSM.
        """
        phase = _current_phase(conversation_state)
        last_asked = conversation_state.get("last_asked_at")
        response = conversation_state.get("last_response")

        if obs is None:
            return Decision(
                action=Action.WAIT,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=phase,
                confidence=0.0,
            )

        num_persons = len(obs.persons)
        has_person = num_persons >= 1

        # --- SEARCH_LOCALIZE: optionally use LLM; fallback FSM
        if phase == Phase.SEARCH_LOCALIZE.value:
            validated = validate_llm_proposal(llm_proposal)
            if validated is not None and validated.get("confidence", 0) >= 0.6:
                return _decision_from_llm_proposal(validated, phase)
            # FSM fallback
            if has_person and obs.confidence >= 0.5:
                return Decision(
                    action=Action.STOP,
                    params={},
                    say=None,
                    wait_for_response_s=None,
                    mode=Phase.APPROACH_CONFIRM.value,
                    confidence=obs.confidence,
                )
            return Decision(
                action=Action.ROTATE_RIGHT,
                params={"duration_s": 0.5},
                say=None,
                wait_for_response_s=None,
                mode=Phase.SEARCH_LOCALIZE.value,
                confidence=0.5,
            )

        # --- APPROACH_CONFIRM: navigate, re-detect, confirm. Exit: standoff (centered + high conf) → SCENE_SAFETY_TRIAGE
        if phase == Phase.APPROACH_CONFIRM.value:
            if not has_person:
                return Decision(
                    action=Action.WAIT,
                    params={},
                    say=None,
                    wait_for_response_s=None,
                    mode=Phase.SEARCH_LOCALIZE.value,
                    confidence=0.3,
                )
            if abs(obs.primary_person_center_offset) <= CENTER_OFFSET_THRESHOLD and obs.confidence >= 0.6:
                return Decision(
                    action=Action.STOP,
                    params={},
                    say=None,
                    wait_for_response_s=None,
                    mode=Phase.SCENE_SAFETY_TRIAGE.value,
                    confidence=obs.confidence,
                )
            if abs(obs.primary_person_center_offset) <= CENTER_OFFSET_THRESHOLD:
                return Decision(
                    action=Action.FORWARD_SLOW,
                    params={},
                    say=None,
                    wait_for_response_s=None,
                    mode=Phase.APPROACH_CONFIRM.value,
                    confidence=obs.confidence,
                )
            return Decision(
                action=Action.ROTATE_LEFT if obs.primary_person_center_offset > 0 else Action.ROTATE_RIGHT,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=Phase.APPROACH_CONFIRM.value,
                confidence=obs.confidence,
            )

        # --- SCENE_SAFETY_TRIAGE: quick hazard scan, choose viewpoints. Exit: safe enough → DEBRIS or INJURY
        if phase == Phase.SCENE_SAFETY_TRIAGE.value:
            return Decision(
                action=Action.STOP,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=Phase.INJURY_DETECTION.value,
                confidence=obs.confidence,
            )

        # --- DEBRIS_ASSESSMENT: rubble detect, movable vs not. Exit: access improved | not movable → INJURY
        if phase == Phase.DEBRIS_ASSESSMENT.value:
            return Decision(
                action=Action.WAIT,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=Phase.INJURY_DETECTION.value,
                confidence=obs.confidence,
            )

        # --- INJURY_DETECTION: injury report. Exit: report complete → ASSIST_COMMUNICATE
        if phase == Phase.INJURY_DETECTION.value:
            return Decision(
                action=Action.STOP,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=Phase.ASSIST_COMMUNICATE.value,
                confidence=obs.confidence,
            )

        # --- ASSIST_COMMUNICATE: LLM-driven when available (intelligent responses); else triage script
        if phase == Phase.ASSIST_COMMUNICATE.value:
            # No response after 2 repeats → assume victim cannot talk; skip triage, visual inspection only
            if conversation_state.get("assume_cannot_talk"):
                return Decision(
                    action=Action.SAY,
                    params={},
                    say="No response detected. I'll proceed with visual inspection only and send what I see to the command center.",
                    wait_for_response_s=None,
                    mode=Phase.SCAN_CAPTURE.value,
                    confidence=obs.confidence,
                )
            # Use LLM proposal for intelligent, contextual dialogue when confidence is sufficient
            validated = validate_llm_proposal(llm_proposal)
            if validated is not None and validated.get("confidence", 0) >= 0.5:
                action_str = validated.get("action", "")
                if action_str in ("ask", "say") and validated.get("say"):
                    return _decision_from_llm_proposal(validated, phase)
            step_index = int(conversation_state.get("triage_step_index", 0))
            triage_answers = dict(conversation_state.get("triage_answers") or {})
            response = conversation_state.get("last_response")

            # If we have a new response: parse for current step, advance, then output next step in same decision
            if response is not None and response.strip():
                step = get_step(step_index)
                if isinstance(step, TriageStep):
                    parsed = parse_for_step(response, step.expected_answer_type, step.key)
                    if parsed is not None:
                        triage_answers[step.key] = parsed
                next_index = step_index + 1
                next_step = get_step(next_index)
                if next_step is None:
                    # Triage complete → SCAN_CAPTURE
                    return Decision(
                        action=Action.SAY,
                        params={
                            "triage_step_index": next_index,
                            "triage_answers_delta": triage_answers,
                            "clear_last_response": True,
                        },
                        say="Thank you. I'm going to scan you and capture images now. Please stay still.",
                        wait_for_response_s=None,
                        mode=Phase.SCAN_CAPTURE.value,
                        confidence=obs.confidence,
                    )
                if is_acknowledge_step(next_index):
                    return Decision(
                        action=Action.SAY,
                        params={
                            "triage_step_index": next_index + 1,
                            "triage_answers_delta": triage_answers,
                            "clear_last_response": True,
                        },
                        say=TRIAGE_ACKNOWLEDGE_SAY,
                        wait_for_response_s=None,
                        mode=Phase.ASSIST_COMMUNICATE.value,
                        confidence=obs.confidence,
                    )
                if isinstance(next_step, TriageStep):
                    return Decision(
                        action=Action.ASK,
                        params={
                            "triage_step_index": next_index,
                            "triage_answers_delta": triage_answers,
                            "clear_last_response": True,
                            "last_prompt": next_step.question,
                        },
                        say=next_step.question,
                        wait_for_response_s=8.0,
                        mode=Phase.ASSIST_COMMUNICATE.value,
                        confidence=obs.confidence,
                    )

            # No response yet: output current step
            step = get_step(step_index)
            if step is None:
                return Decision(
                    action=Action.SAY,
                    params={},
                    say="Thank you. I'm going to scan you and capture images now. Please stay still.",
                    wait_for_response_s=None,
                    mode=Phase.SCAN_CAPTURE.value,
                    confidence=obs.confidence,
                )
            if is_acknowledge_step(step_index):
                return Decision(
                    action=Action.SAY,
                    params={"triage_step_index": step_index + 1, "clear_last_response": True},
                    say=TRIAGE_ACKNOWLEDGE_SAY,
                    wait_for_response_s=None,
                    mode=Phase.ASSIST_COMMUNICATE.value,
                    confidence=obs.confidence,
                )
            if isinstance(step, TriageStep):
                return Decision(
                    action=Action.ASK,
                    params={"last_prompt": step.question},
                    say=step.question,
                    wait_for_response_s=8.0,
                    mode=Phase.ASSIST_COMMUNICATE.value,
                    confidence=obs.confidence,
                )
            return Decision(
                action=Action.WAIT,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=Phase.ASSIST_COMMUNICATE.value,
                confidence=obs.confidence,
            )

        # --- SCAN_CAPTURE: placeholder capture views; agent runs capture_image and sets images_captured
        if phase == Phase.SCAN_CAPTURE.value:
            return Decision(
                action=Action.SAY,
                params={"capture_views": ["front", "left", "right", "scene"]},
                say="Images captured. Preparing report for the command center.",
                wait_for_response_s=None,
                mode=Phase.REPORT_SEND.value,
                confidence=obs.confidence,
            )

        # --- REPORT_SEND: build report payload; agent POSTs to command center /report
        if phase == Phase.REPORT_SEND.value:
            import time as _t
            triage_answers = dict(conversation_state.get("triage_answers") or {})
            images_captured = list(conversation_state.get("images_captured") or [])
            location_hint = getattr(obs, "scene_caption", None) or "unknown"
            report_payload = {
                "incident_id": f"incident_{int(_t.time() * 1000)}",
                "timestamp": obs.timestamp if obs else 0,
                "patient_summary": triage_answers,
                "hazards": [],
                "images": images_captured,
                "location_hint": location_hint,
                "confidence": obs.confidence if obs else 0.0,
            }
            return Decision(
                action=Action.SAY,
                params={"report_payload": report_payload, "send_report": True},
                say="Noted — report and images sent to the command center. Stay with me. If anything changes, tell me.",
                wait_for_response_s=None,
                mode=Phase.HANDOFF_ESCORT.value,
                confidence=1.0,
            )

        # --- HANDOFF_ESCORT: multi-victim or escort. Exit: mission command → DONE or back to SEARCH
        if phase == Phase.HANDOFF_ESCORT.value:
            return Decision(
                action=Action.STOP,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=Phase.DONE.value,
                confidence=1.0,
            )

        if phase == Phase.DONE.value:
            return Decision(
                action=Action.STOP,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=Phase.DONE.value,
                confidence=1.0,
            )

        # BOOT is handled in agent; unknown phase default to search
        return Decision(
            action=Action.WAIT,
            params={},
            say=None,
            wait_for_response_s=None,
            mode=Phase.SEARCH_LOCALIZE.value,
            confidence=0.0,
        )
