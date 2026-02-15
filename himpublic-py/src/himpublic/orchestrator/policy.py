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
from himpublic.orchestrator.medic_dialogue import (
    summarize_answer,
    ack_sentence,
    get_body_part_followup_question,
    should_insert_body_part_followup,
)
from himpublic.orchestrator.dialogue_manager import TriageDialogueManager


class Action(Enum):
    STOP = "stop"
    ROTATE_LEFT = "rotate_left"
    ROTATE_RIGHT = "rotate_right"
    FORWARD_SLOW = "forward_slow"
    BACK_UP = "back_up"
    WAIT = "wait"
    ASK = "ask"
    SAY = "say"
    WAVE = "wave"  # hand wave gesture (used to signal rubble removal action)


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

        # --- SEARCH_LOCALIZE: scan for rubble/debris, announce when found
        if phase == Phase.SEARCH_LOCALIZE.value:
            # If camera sees an object (rubble) with decent confidence → transition to DEBRIS_ASSESSMENT
            if has_person and obs.confidence >= 0.3:
                detected_name = obs.persons[0].cls_name if obs.persons else "debris"
                return Decision(
                    action=Action.SAY,
                    params={"search_sub_phase": "found"},
                    say=f"I see rubble ahead. It looks like {detected_name}. Let me take a closer look.",
                    wait_for_response_s=None,
                    mode=Phase.DEBRIS_ASSESSMENT.value,
                    confidence=obs.confidence,
                )

            # Sub-phase state machine within SEARCH_LOCALIZE
            search_sub = conversation_state.get("search_sub_phase", "announce")
            now = float(conversation_state.get("now") or 0.0)

            # --- Sub-phase 1: "announce" – say "Scanning for rubble" out loud (once)
            if search_sub == "announce":
                return Decision(
                    action=Action.SAY,
                    params={"search_sub_phase": "scanning"},
                    say="Scanning the area for rubble and debris. Looking around now.",
                    wait_for_response_s=None,
                    mode=Phase.SEARCH_LOCALIZE.value,
                    confidence=0.5,
                )

            # --- Sub-phase 2: "scanning" – keep looking, periodically announce
            if search_sub == "scanning":
                # Default: wait and keep scanning
                return Decision(
                    action=Action.WAIT,
                    params={"search_sub_phase": "scanning"},
                    say=None,
                    wait_for_response_s=None,
                    mode=Phase.SEARCH_LOCALIZE.value,
                    confidence=0.3,
                )

            # Fallback
            return Decision(
                action=Action.WAIT,
                params={"search_sub_phase": "scanning"},
                say=None,
                wait_for_response_s=None,
                mode=Phase.SEARCH_LOCALIZE.value,
                confidence=0.3,
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

        # --- DEBRIS_ASSESSMENT: wave hand to signal rubble removal, then transition to communicate
        if phase == Phase.DEBRIS_ASSESSMENT.value:
            search_sub = conversation_state.get("search_sub_phase", "assess_announce")
            now = float(conversation_state.get("now") or 0.0)
            phase_entered = conversation_state.get("phase_entered_at") or now
            elapsed_in_phase = now - phase_entered if now and phase_entered else 0.0

            # First: announce assessment
            if search_sub != "wave_done" and elapsed_in_phase < 2.0:
                return Decision(
                    action=Action.SAY,
                    params={"search_sub_phase": "do_wave"},
                    say="I found debris blocking the area. Let me try to clear it.",
                    wait_for_response_s=None,
                    mode=Phase.DEBRIS_ASSESSMENT.value,
                    confidence=obs.confidence,
                )

            # Then: wave hand (removing rubble gesture)
            if search_sub == "do_wave":
                return Decision(
                    action=Action.WAVE,
                    params={"search_sub_phase": "wave_done", "wave_hand": "right", "wave_cycles": 2},
                    say="Clearing rubble now.",
                    wait_for_response_s=None,
                    mode=Phase.DEBRIS_ASSESSMENT.value,
                    confidence=obs.confidence,
                )

            # After wave: announce completion and transition to ASSIST_COMMUNICATE
            return Decision(
                action=Action.SAY,
                params={"search_sub_phase": "announce"},
                say="I have cleared some of the rubble. Let me assess the situation and report to the team.",
                wait_for_response_s=None,
                mode=Phase.ASSIST_COMMUNICATE.value,
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

        # --- ASSIST_COMMUNICATE: slot-based dialogue manager (replaces linear triage script)
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

            response = conversation_state.get("last_response")
            last_ack = conversation_state.get("last_answer_acknowledged", False)
            pending_id = conversation_state.get("pending_question_id")
            pending_asked_at = conversation_state.get("pending_question_asked_at")
            pending_retries = int(conversation_state.get("pending_question_retries", 0))
            current_key = conversation_state.get("current_question_key")
            now = float(conversation_state.get("now") or 0.0)
            wait_window_s = 15.0

            # Get or create the dialogue manager (stored on conversation_state by agent)
            dm: TriageDialogueManager | None = conversation_state.get("_dialogue_manager")
            if dm is None:
                dm = TriageDialogueManager()
                # Store it back (agent.py will persist this)
                conversation_state["_dialogue_manager"] = dm

            # 1) We have a victim response → process it through the dialogue manager
            if response is not None and response.strip() and not last_ack:
                result = dm.process_turn(response, current_key, now)
                triage_answers = result["triage_answers"]
                robot_say = result["robot_utterance"]
                cc_payload = result["command_center_payload"]
                next_q_key = result["question_key"]
                next_q_text = result["question_text"]
                triage_complete = result["triage_complete"]

                # Build params: store extracted facts, clear pending, prepare next question
                params: dict[str, Any] = {
                    "triage_answers_delta": triage_answers,
                    "last_answer_acknowledged": True,
                    "clear_pending_question": True,
                    "clear_last_response": True,
                }

                if cc_payload is not None:
                    params["send_triage_update"] = True
                    params["triage_update_payload"] = cc_payload

                if triage_complete:
                    return Decision(
                        action=Action.SAY,
                        params=params,
                        say=robot_say or "Thank you. I'm going to scan your body and capture a few images for the medics. Please stay still.",
                        wait_for_response_s=None,
                        mode=Phase.SCAN_CAPTURE.value,
                        confidence=obs.confidence,
                    )

                # Robot says ack + next question in one turn
                if next_q_key and next_q_text:
                    params["set_pending_question"] = True
                    params["pending_question_id"] = f"dm_{next_q_key}"
                    params["pending_question_text"] = next_q_text
                    params["current_question_key"] = next_q_key
                    params["pending_question_retries"] = 0
                    params["last_prompt"] = next_q_text
                    params["last_answer_acknowledged"] = False
                    return Decision(
                        action=Action.ASK,
                        params=params,
                        say=robot_say,
                        wait_for_response_s=wait_window_s,
                        mode=Phase.ASSIST_COMMUNICATE.value,
                        confidence=obs.confidence,
                    )

                # No more questions but not complete (shouldn't happen normally)
                return Decision(
                    action=Action.SAY,
                    params=params,
                    say=robot_say,
                    wait_for_response_s=None,
                    mode=Phase.ASSIST_COMMUNICATE.value,
                    confidence=obs.confidence,
                )

            # 2) Waiting for response: pending question set and no response yet
            if pending_id and response is None and pending_asked_at is not None:
                elapsed = now - pending_asked_at if now else 0.0
                if elapsed < wait_window_s:
                    return Decision(
                        action=Action.WAIT,
                        params={},
                        say=None,
                        wait_for_response_s=None,
                        mode=Phase.ASSIST_COMMUNICATE.value,
                        confidence=obs.confidence,
                    )
                # Timeout: retry once or give up
                if pending_retries < 1:
                    retry_phrase = f"I didn't catch that. {conversation_state.get('pending_question_text', '')}"
                    return Decision(
                        action=Action.ASK,
                        params={
                            "set_pending_question": True,
                            "pending_question_id": pending_id,
                            "pending_question_text": conversation_state.get("pending_question_text"),
                            "current_question_key": current_key,
                            "pending_question_retries": pending_retries + 1,
                            "last_prompt": retry_phrase,
                        },
                        say=retry_phrase,
                        wait_for_response_s=wait_window_s,
                        mode=Phase.ASSIST_COMMUNICATE.value,
                        confidence=obs.confidence,
                    )
                return Decision(
                    action=Action.SAY,
                    params={},
                    say="I'm not hearing you clearly. I will continue with visual documentation and send what I see.",
                    wait_for_response_s=None,
                    mode=Phase.SCAN_CAPTURE.value,
                    confidence=obs.confidence,
                )

            # 3) No pending question and no response yet → ask first/next question via dialogue manager
            result = dm.process_turn(None, current_key, now)
            next_q_key = result["question_key"]
            next_q_text = result["question_text"]
            robot_say = result["robot_utterance"]
            triage_complete = result["triage_complete"]

            if triage_complete:
                return Decision(
                    action=Action.SAY,
                    params={"triage_answers_delta": result["triage_answers"]},
                    say="Thank you. I'm going to scan your body and capture a few images for the medics. Please stay still.",
                    wait_for_response_s=None,
                    mode=Phase.SCAN_CAPTURE.value,
                    confidence=obs.confidence,
                )

            if next_q_key and next_q_text:
                return Decision(
                    action=Action.ASK,
                    params={
                        "set_pending_question": True,
                        "pending_question_id": f"dm_{next_q_key}",
                        "pending_question_text": next_q_text,
                        "current_question_key": next_q_key,
                        "last_prompt": next_q_text,
                        "pending_question_retries": 0,
                    },
                    say=robot_say,
                    wait_for_response_s=wait_window_s,
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

        # --- REPORT_SEND: build report payload and human-readable document; agent POSTs to command center /report
        if phase == Phase.REPORT_SEND.value:
            import time as _t
            triage_answers = dict(conversation_state.get("triage_answers") or {})
            images_captured = list(conversation_state.get("images_captured") or [])
            location_hint = getattr(obs, "scene_caption", None) or "unknown"
            incident_id = f"incident_{int(_t.time() * 1000)}"
            # Build a short document summary for the command center UI
            doc_lines = [
                f"# Incident Report: {incident_id}",
                "",
                "## Patient summary",
                *([f"- **{k}:** {v}" for k, v in triage_answers.items()] if triage_answers else ["- No triage answers yet."]),
                "",
                "## Location",
                f"- {location_hint}",
                "",
                "## Evidence",
                f"- Images captured: {len(images_captured)}",
            ]
            report_payload = {
                "incident_id": incident_id,
                "timestamp": obs.timestamp if obs else 0,
                "patient_summary": triage_answers,
                "hazards": [],
                "images": images_captured,
                "location_hint": location_hint,
                "confidence": obs.confidence if obs else 0.0,
                "document": "\n".join(doc_lines),
            }
            return Decision(
                action=Action.SAY,
                params={"report_payload": report_payload, "send_report": True},
                say="Report and images sent to the command center. I'm staying with you. If anything changes, tell me immediately.",
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
