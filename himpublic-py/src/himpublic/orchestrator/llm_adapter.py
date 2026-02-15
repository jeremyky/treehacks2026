"""
LLM adapter: propose structured actions for the robot policy.
Uses OpenAI chat completion with strict JSON output. No motor control—outputs only
action enum, optional say/wait_for_response_s/next_phase, and confidence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from himpublic.perception.types import Observation

logger = logging.getLogger(__name__)

# Allowed action strings (must match policy.Action enum values)
ALLOWED_ACTIONS = frozenset({
    "stop", "rotate_left", "rotate_right", "forward_slow",
    "back_up", "wait", "ask", "say",
})

# JSON schema for structured output (OpenAI response_format, strict mode compatible)
def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}

ACTION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(ALLOWED_ACTIONS),
            "description": "Exactly one of the allowed robot actions.",
        },
        "say": _nullable({
            "type": "string",
            "description": "Optional phrase for TTS when action is ask or say.",
        }),
        "wait_for_response_s": _nullable({
            "type": "number",
            "description": "Optional seconds to listen for response (0-10). Only for ask.",
        }),
        "next_phase": _nullable({
            "type": "string",
            "description": "Optional next phase value if transitioning.",
        }),
        "confidence": {
            "type": "number",
            "description": "Confidence in this decision, 0 to 1.",
        },
    },
    "required": ["action", "say", "wait_for_response_s", "next_phase", "confidence"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You are a disaster response robot performing search and rescue triage.

Your role: propose the next robot action based on observation and conversation state.
You must output valid JSON only. Safety is critical—never invent new actions.

Allowed actions (use exactly these strings):
- stop
- rotate_left
- rotate_right
- forward_slow
- back_up
- wait
- ask   (robot speaks and listens; set "say" and optionally "wait_for_response_s")
- say   (robot speaks only; set "say")

Rules:
- Output only valid JSON matching the required schema.
- action must be exactly one of the allowed actions above.
- confidence must be between 0 and 1.
- If using ask or say, provide a short "say" phrase (one sentence).
- wait_for_response_s: only for ask; use 10-18 seconds so the victim has time to respond.
- next_phase: only use known phases: search_localize, approach_confirm, scene_safety_triage, debris_assessment, injury_detection, assist_communicate, handoff_escort, done.
- Do not invent new action or phase names."""


def _obs_summary(obs: Observation | None) -> dict[str, Any]:
    """Minimal observation summary for the LLM prompt."""
    if obs is None:
        return {"num_persons": 0, "confidence": 0.0, "primary_person_center_offset": 0.0}
    return {
        "num_persons": len(obs.persons),
        "confidence": obs.confidence,
        "primary_person_center_offset": getattr(obs, "primary_person_center_offset", 0.0),
        "obstacle_distance_m": getattr(obs, "obstacle_distance_m", None),
    }


def _build_user_message(obs: Observation | None, conversation_state: dict[str, Any]) -> str:
    """Build user message for the model. Include triage context in assist_communicate."""
    summary = _obs_summary(obs)
    phase = conversation_state.get("phase") or conversation_state.get("mode")
    conv_state: dict[str, Any] = {
        "phase": phase,
        "last_response": conversation_state.get("last_response"),
        "last_asked_at": conversation_state.get("last_asked_at"),
    }
    if phase == "assist_communicate":
        conv_state["last_prompt"] = conversation_state.get("last_prompt")
        conv_state["triage_answers"] = conversation_state.get("triage_answers") or {}
        conv_state["triage_step_index"] = conversation_state.get("triage_step_index", 0)
    parts = [
        "Current observation summary:",
        json.dumps(summary, indent=0),
        "",
        "Conversation state:",
        json.dumps(conv_state, indent=0),
    ]
    if phase == "assist_communicate":
        parts.extend([
            "",
            "You are talking to a victim during triage. Use their last_response and triage_answers to ask one short, empathetic follow-up question. Speak naturally (e.g. 'Can you tell me where it hurts?' or 'How is your breathing?'). Use action 'ask' with wait_for_response_s between 12 and 18 so they have time to respond.",
        ])
    parts.extend([
        "",
        "Respond with a single JSON object: action, say (optional), wait_for_response_s (optional), next_phase (optional), confidence.",
    ])
    return "\n".join(parts)


def _parse_response(content: str) -> dict[str, Any] | None:
    """Parse model content to dict. Returns None if invalid."""
    if not content or not content.strip():
        return None
    content = content.strip()
    # Handle optional markdown code block
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)
    try:
        out = json.loads(content)
        if not isinstance(out, dict):
            return None
        if "action" not in out or "confidence" not in out:
            return None
        return out
    except json.JSONDecodeError:
        return None


def propose_action(
    obs: Observation | None,
    conversation_state: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str = "gpt-4o-mini",
    temperature: float = 0.3,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    """
    Call OpenAI to propose a structured action. Returns dict with action, say,
    wait_for_response_s, next_phase, confidence—or None on failure or invalid output.

    Intended to be called from a thread/executor so it may block; do not call
    directly from the async event loop without run_in_executor.
    """
    key = api_key or __import__("os").environ.get("OPENAI_API_KEY")
    if not key:
        logger.debug("No OpenAI API key; skipping LLM proposal.")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed; pip install openai")
        return None

    client = OpenAI(api_key=key)
    user_msg = _build_user_message(obs, conversation_state)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=max(0.0, min(0.4, temperature)),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "robot_action",
                        "strict": True,
                        "schema": ACTION_RESPONSE_SCHEMA,
                    },
                },
            )
            choice = response.choices and response.choices[0]
            if not choice or not getattr(choice.message, "content", None):
                logger.warning("LLM returned empty content (attempt %s)", attempt + 1)
                continue
            parsed = _parse_response(choice.message.content)
            if parsed is not None:
                return parsed
            logger.warning("LLM output invalid JSON (attempt %s): %s", attempt + 1, choice.message.content[:200])
        except Exception as e:
            logger.warning("LLM request failed (attempt %s): %s", attempt + 1, e)

    return None
