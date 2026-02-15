"""
LLM-powered dialogue manager for medical triage Q&A.

Uses OpenAI to dynamically:
- Extract structured facts ("slots") from victim utterances.
- Generate concise, empathetic robot responses following MARCH protocol.
- Decide the next question based on missing high-priority medical information.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums for structured slot values
# ---------------------------------------------------------------------------

class Consciousness(Enum):
    UNKNOWN = "unknown"
    ALERT = "alert"
    VERBAL = "verbal"
    PAIN = "pain"
    UNRESPONSIVE = "unresponsive"


class BleedingSeverity(Enum):
    UNKNOWN = "unknown"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class SlotConfidence(Enum):
    """How confident we are in a slot value."""
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# A) Patient state: structured medical slots
# ---------------------------------------------------------------------------

@dataclass
class PatientState:
    """Structured facts about the victim, extracted from dialogue."""
    needs_help: bool | None = None  # None = unknown
    major_bleeding: bool | None = None
    bleeding_location: str | None = None  # e.g. "left leg"
    bleeding_severity: BleedingSeverity = BleedingSeverity.UNKNOWN
    conscious: Consciousness = Consciousness.UNKNOWN
    breathing_distress: bool | None = None
    chest_injury: bool | None = None
    trapped_or_cant_move: bool | None = None
    pain_locations: list[str] = field(default_factory=list)
    pain_score: int | None = None  # 0-10
    hazards_present: list[str] = field(default_factory=list)
    head_injury: bool | None = None
    shock_signs: bool | None = None  # dizzy, faint, cold/clammy
    feeling_cold: bool | None = None
    other_wounds: str | None = None
    consent_photos: bool | None = None
    location_hint: str | None = None  # where victim says they are
    notes_freeform: str = ""

    # Confidence per slot (keys must match field names above)
    _confidences: dict[str, SlotConfidence] = field(default_factory=dict)

    def get_confidence(self, slot: str) -> SlotConfidence:
        return self._confidences.get(slot, SlotConfidence.UNKNOWN)

    def set_slot(self, slot: str, value: Any, confidence: SlotConfidence = SlotConfidence.HIGH) -> None:
        """Set a slot value and its confidence, respecting partial-update rules."""
        current = getattr(self, slot, None)
        current_conf = self.get_confidence(slot)

        # Don't overwrite a HIGH-confidence value with a LOW one unless the new value conflicts
        if current_conf == SlotConfidence.HIGH and confidence == SlotConfidence.LOW:
            if current is not None and current != value:
                return  # keep existing high-confidence value
        setattr(self, slot, value)
        self._confidences[slot] = confidence

    def known_slots(self) -> dict[str, Any]:
        """Return a dict of all slots that have known (non-None, non-unknown) values."""
        result: dict[str, Any] = {}
        for slot_name in _SLOT_NAMES:
            val = getattr(self, slot_name, None)
            if val is None:
                continue
            if isinstance(val, Enum) and val.value == "unknown":
                continue
            if isinstance(val, list) and not val:
                continue
            if isinstance(val, str) and not val:
                continue
            result[slot_name] = val.value if isinstance(val, Enum) else val
        return result

    def to_dict(self) -> dict[str, Any]:
        """Full serializable dict for command center."""
        d: dict[str, Any] = {}
        for slot_name in _SLOT_NAMES:
            val = getattr(self, slot_name, None)
            if isinstance(val, Enum):
                d[slot_name] = val.value
            elif isinstance(val, list):
                d[slot_name] = list(val)
            else:
                d[slot_name] = val
        return d


# All slot field names (order matches dataclass definition, minus private fields)
_SLOT_NAMES = [
    "needs_help", "major_bleeding", "bleeding_location", "bleeding_severity",
    "conscious", "breathing_distress", "chest_injury", "trapped_or_cant_move",
    "pain_locations", "pain_score", "hazards_present", "head_injury",
    "shock_signs", "feeling_cold", "other_wounds", "consent_photos",
    "location_hint", "notes_freeform",
]


# ---------------------------------------------------------------------------
# B) Dialogue state: conversation tracking
# ---------------------------------------------------------------------------

@dataclass
class DialogueState:
    """Tracks dialogue flow, question history, and command-center update dedup."""
    turn_index: int = 0
    last_question_key: str | None = None
    asked_question_keys: dict[str, float] = field(default_factory=dict)  # key -> timestamp
    asked_question_turns: dict[str, int] = field(default_factory=dict)  # key -> turn_index
    last_command_center_payload_hash: str = ""
    last_update_time: float = 0.0
    conversation_history: list[dict[str, str]] = field(default_factory=list)  # [{"role": ..., "content": ...}]


# ---------------------------------------------------------------------------
# C) LLM-powered triage: system prompt + structured output
# ---------------------------------------------------------------------------

_TRIAGE_SYSTEM_PROMPT = """\
You are a disaster-response rescue robot conducting medical triage on an injured victim at a disaster site.

PROTOCOL — Follow MARCH triage order strictly. Address life-threats first:
  1. M — Massive hemorrhage: Is there heavy bleeding? Where? How severe?
  2. A — Airway: Can the victim speak clearly?
  3. R — Respiration: Any breathing difficulty? Chest wounds?
  4. C — Circulation: Signs of shock (dizzy, faint, cold/clammy)? Trapped/pinned?
  5. H — Head injury / Hypothermia: Head trauma? Feeling very cold?
After MARCH, ask about: pain location/score, other wounds, hazards nearby, and consent for photos.

RESPONSE RULES:
- Maximum 2 sentences total. First sentence: brief acknowledgment of what the victim just said. Second sentence: your next question.
- If the victim has not spoken yet (first contact), ask only ONE question — start with "Can you hear me? Are you hurt?"
- Be calm, direct, and empathetic. Speak like a trained medic, not a chatbot.
- Never use filler words, excessive pleasantries, or long explanations.
- Do NOT repeat a question the victim has already clearly answered.
- If the victim volunteers information about multiple topics, extract all of it — don't ignore details.
- Ask ONE question at a time. Do not combine multiple medical topics in one question.

TRIAGE COMPLETION — set triage_complete to true ONLY when ALL of these slots have been assessed (are non-null in the patient state OR were just extracted):
  needs_help, major_bleeding, conscious, breathing_distress, chest_injury,
  shock_signs, head_injury, trapped_or_cant_move, pain_score, consent_photos.
  (Plus bleeding_location and bleeding_severity if major_bleeding is true.)
If ANY of these are still unknown/null, you MUST continue asking. Do NOT end triage early.
When triage IS complete, tell the victim you will now do a visual scan.

CURRENT PATIENT STATE (already known facts — do NOT re-ask these):
{patient_state_json}

You must respond with a JSON object matching this exact schema:
{{
  "extracted_facts": {{
    "needs_help": true/false/null,
    "major_bleeding": true/false/null,
    "bleeding_location": "string or null",
    "bleeding_severity": "mild"/"moderate"/"severe"/null,
    "conscious": "alert"/"verbal"/"pain"/"unresponsive"/null,
    "breathing_distress": true/false/null,
    "chest_injury": true/false/null,
    "trapped_or_cant_move": true/false/null,
    "pain_locations": ["string"] or null,
    "pain_score": 0-10 or null,
    "head_injury": true/false/null,
    "shock_signs": true/false/null,
    "feeling_cold": true/false/null,
    "other_wounds": "string or null",
    "hazards_present": ["string"] or null,
    "consent_photos": true/false/null
  }},
  "robot_utterance": "Your spoken response — max 2 sentences",
  "next_question_key": "the medical topic you are asking about (e.g. major_bleeding, breathing_distress, pain) or null if done",
  "triage_complete": false
}}

Rules for extracted_facts:
- Only set a field if the victim's latest message CLEARLY provides that information. Use null for anything not mentioned.
- For bleeding_severity use exactly: "mild", "moderate", or "severe".
- For conscious use exactly: "alert", "verbal", "pain", or "unresponsive".
- pain_locations should be a list of body part strings. hazards_present should be a list of hazard type strings.
- pain_score must be an integer 0-10.
"""

# JSON schema for OpenAI structured output (strict mode compatible — uses anyOf for nullable)
def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}

_TRIAGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "extracted_facts": {
            "type": "object",
            "properties": {
                "needs_help": _nullable({"type": "boolean"}),
                "major_bleeding": _nullable({"type": "boolean"}),
                "bleeding_location": _nullable({"type": "string"}),
                "bleeding_severity": _nullable({"type": "string", "enum": ["mild", "moderate", "severe"]}),
                "conscious": _nullable({"type": "string", "enum": ["alert", "verbal", "pain", "unresponsive"]}),
                "breathing_distress": _nullable({"type": "boolean"}),
                "chest_injury": _nullable({"type": "boolean"}),
                "trapped_or_cant_move": _nullable({"type": "boolean"}),
                "pain_locations": _nullable({"type": "array", "items": {"type": "string"}}),
                "pain_score": _nullable({"type": "integer"}),
                "head_injury": _nullable({"type": "boolean"}),
                "shock_signs": _nullable({"type": "boolean"}),
                "feeling_cold": _nullable({"type": "boolean"}),
                "other_wounds": _nullable({"type": "string"}),
                "hazards_present": _nullable({"type": "array", "items": {"type": "string"}}),
                "consent_photos": _nullable({"type": "boolean"}),
            },
            "required": [
                "needs_help", "major_bleeding", "bleeding_location", "bleeding_severity",
                "conscious", "breathing_distress", "chest_injury", "trapped_or_cant_move",
                "pain_locations", "pain_score", "head_injury", "shock_signs",
                "feeling_cold", "other_wounds", "hazards_present", "consent_photos",
            ],
            "additionalProperties": False,
        },
        "robot_utterance": {"type": "string"},
        "next_question_key": _nullable({"type": "string"}),
        "triage_complete": {"type": "boolean"},
    },
    "required": ["extracted_facts", "robot_utterance", "next_question_key", "triage_complete"],
    "additionalProperties": False,
}

_MAX_CONVERSATION_HISTORY = 20  # keep last N messages for context


def _call_triage_llm(
    patient_state: PatientState,
    conversation_history: list[dict[str, str]],
    api_key: str | None = None,
    model: str = "gpt-4o-mini",
) -> dict[str, Any] | None:
    """
    Call OpenAI to process one triage turn.

    Returns parsed JSON dict or None on failure.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        logger.debug("No OpenAI API key; LLM triage unavailable.")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed; pip install openai")
        return None

    # Build system prompt with current patient state
    known = patient_state.known_slots()
    state_json = json.dumps(known, indent=2, default=str) if known else "{}"
    system_prompt = _TRIAGE_SYSTEM_PROMPT.format(patient_state_json=state_json)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    # Add conversation history (last N turns)
    messages.extend(conversation_history[-_MAX_CONVERSATION_HISTORY:])

    client = OpenAI(api_key=key)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "triage_response",
                        "strict": True,
                        "schema": _TRIAGE_RESPONSE_SCHEMA,
                    },
                },
            )
            choice = response.choices and response.choices[0]
            if not choice or not getattr(choice.message, "content", None):
                logger.warning("LLM triage returned empty content (attempt %s)", attempt + 1)
                continue

            content = choice.message.content.strip()
            # Handle markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)

            parsed = json.loads(content)
            if isinstance(parsed, dict) and "extracted_facts" in parsed and "robot_utterance" in parsed:
                return parsed
            logger.warning("LLM triage output missing required fields (attempt %s)", attempt + 1)
        except json.JSONDecodeError as e:
            logger.warning("LLM triage JSON parse error (attempt %s): %s", attempt + 1, e)
        except Exception as e:
            logger.warning("LLM triage request failed (attempt %s): %s", attempt + 1, e)

    return None


def _apply_extracted_facts(
    patient_state: PatientState,
    extracted_facts: dict[str, Any],
) -> dict[str, Any]:
    """
    Apply LLM-extracted facts to patient state. Returns dict of new facts actually applied.
    """
    new_facts: dict[str, Any] = {}

    for slot_name, value in extracted_facts.items():
        if value is None:
            continue

        # Map string enums to their Enum types
        if slot_name == "bleeding_severity" and isinstance(value, str):
            try:
                value = BleedingSeverity(value)
            except ValueError:
                continue
        elif slot_name == "conscious" and isinstance(value, str):
            try:
                value = Consciousness(value)
            except ValueError:
                continue

        # Handle list slots (pain_locations, hazards_present) — merge, don't overwrite
        if slot_name == "pain_locations" and isinstance(value, list):
            for loc in value:
                if loc and loc not in patient_state.pain_locations:
                    patient_state.pain_locations.append(loc)
            if value:
                new_facts["pain_locations"] = list(patient_state.pain_locations)
            continue

        if slot_name == "hazards_present" and isinstance(value, list):
            for h in value:
                if h and h not in patient_state.hazards_present:
                    patient_state.hazards_present.append(h)
            if value:
                new_facts["hazards_present"] = list(patient_state.hazards_present)
            continue

        # Standard slot: set with HIGH confidence (LLM extraction)
        if hasattr(patient_state, slot_name):
            patient_state.set_slot(slot_name, value, SlotConfidence.HIGH)
            new_facts[slot_name] = value

    return new_facts


# ---------------------------------------------------------------------------
# D) Command-center update dedup
# ---------------------------------------------------------------------------

def build_command_center_update(
    patient_state: PatientState,
    new_facts: dict[str, Any],
    dialogue_state: DialogueState,
    now: float | None = None,
    min_interval_s: float = 5.0,
) -> dict[str, Any] | None:
    """
    Build a command-center update payload only if there's NEW information
    or enough time has passed.

    Returns:
        payload dict if an update should be sent, or None to skip.
    """
    if now is None:
        now = time.monotonic()

    if not new_facts:
        # No new facts; only send periodic heartbeat if we have prior data and enough time passed
        if not dialogue_state.last_update_time:
            return None  # never sent before and no new facts -> skip
        if (now - dialogue_state.last_update_time) < min_interval_s * 6:
            return None  # sent recently, nothing new -> skip

    payload = {
        "event": "triage_update",
        "timestamp": time.time(),
        "patient_state": patient_state.to_dict(),
        "new_facts": {k: v.value if isinstance(v, Enum) else v for k, v in new_facts.items()},
        "known_slots": {k: v.value if isinstance(v, Enum) else v for k, v in patient_state.known_slots().items()},
    }

    # Hash-based dedup
    payload_hash = hashlib.md5(
        json.dumps(payload.get("known_slots", {}), sort_keys=True, default=str).encode()
    ).hexdigest()

    if payload_hash == dialogue_state.last_command_center_payload_hash:
        return None  # duplicate -- don't send

    dialogue_state.last_command_center_payload_hash = payload_hash
    dialogue_state.last_update_time = now
    return payload


# ---------------------------------------------------------------------------
# E) Fallback responses (used when LLM is unavailable)
# ---------------------------------------------------------------------------

_FALLBACK_QUESTIONS = [
    ("needs_help", "Can you hear me? Are you hurt? Do you need help?"),
    ("major_bleeding", "Is there any heavy bleeding right now?"),
    ("breathing_distress", "Are you having trouble breathing?"),
    ("shock_signs", "Do you feel dizzy, faint, or very cold?"),
    ("head_injury", "Did you hit your head or black out?"),
    ("pain", "Where does it hurt most? Rate your pain 0 to 10."),
    ("consent_photos", "Can I take photos to help the medics assess you?"),
]


def _fallback_response(
    patient_state: PatientState,
    dialogue_state: DialogueState,
) -> tuple[str, str | None, str | None, bool]:
    """
    Deterministic fallback when LLM is unavailable.
    Returns (robot_utterance, question_key, question_text, triage_complete).
    """
    asked = set(dialogue_state.asked_question_keys.keys())
    for key, text in _FALLBACK_QUESTIONS:
        if key not in asked:
            return text, key, text, False
    return (
        "Thank you. I will now do a visual scan and send images to the medics.",
        None, None, True,
    )


# ---------------------------------------------------------------------------
# F) Main dialogue manager class
# ---------------------------------------------------------------------------

class TriageDialogueManager:
    """
    LLM-powered stateful dialogue manager for medical triage.
    Call process_turn() each time we get a victim response (or need the next question).
    """

    def __init__(self) -> None:
        self.patient_state = PatientState()
        self.dialogue_state = DialogueState()
        self._initialized = False

    def process_turn(
        self,
        victim_text: str | None,
        current_question_key: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """
        Process one dialogue turn via LLM.

        Args:
            victim_text: What the victim said (None if no response / first turn).
            current_question_key: The question we last asked.
            now: Current time (monotonic).

        Returns:
            dict with keys:
                "question_key": str | None  -- next question to ask
                "question_text": str | None -- next question text
                "robot_utterance": str       -- full robot speech (ack + question)
                "new_facts": dict            -- newly extracted facts
                "command_center_payload": dict | None -- payload to send (or None = skip)
                "triage_complete": bool      -- True if all questions exhausted
                "triage_answers": dict       -- all known patient facts (for backward compat)
        """
        if now is None:
            now = time.monotonic()

        self.dialogue_state.turn_index += 1

        # Add victim's message to conversation history
        if victim_text and victim_text.strip():
            self.dialogue_state.conversation_history.append({
                "role": "user",
                "content": victim_text.strip(),
            })
        elif victim_text is None and not self.dialogue_state.conversation_history:
            # First turn, no victim text — add a placeholder so the LLM knows to start
            self.dialogue_state.conversation_history.append({
                "role": "user",
                "content": "[First contact — victim has not spoken yet. Initiate triage.]",
            })

        # --- Call LLM ---
        llm_result = _call_triage_llm(
            self.patient_state,
            self.dialogue_state.conversation_history,
        )

        if llm_result is not None:
            # Extract and apply facts
            extracted_raw = llm_result.get("extracted_facts", {})
            new_facts = _apply_extracted_facts(self.patient_state, extracted_raw)

            # Append freeform notes from victim text
            if victim_text and victim_text.strip():
                if self.patient_state.notes_freeform:
                    self.patient_state.notes_freeform += f" | {victim_text.strip()}"
                else:
                    self.patient_state.notes_freeform = victim_text.strip()

            robot_utterance = llm_result.get("robot_utterance", "I'm here with you.")
            next_q_key = llm_result.get("next_question_key")
            triage_complete = llm_result.get("triage_complete", False)
        else:
            # Fallback: deterministic response
            logger.warning("LLM unavailable; using fallback triage response.")
            new_facts = {}
            robot_utterance, next_q_key, _, triage_complete = _fallback_response(
                self.patient_state, self.dialogue_state,
            )

        # Record question key
        if next_q_key:
            self.dialogue_state.asked_question_keys[next_q_key] = now
            self.dialogue_state.asked_question_turns[next_q_key] = self.dialogue_state.turn_index
            self.dialogue_state.last_question_key = next_q_key

        # Add robot's response to conversation history
        self.dialogue_state.conversation_history.append({
            "role": "assistant",
            "content": robot_utterance,
        })

        # Trim conversation history
        if len(self.dialogue_state.conversation_history) > _MAX_CONVERSATION_HISTORY:
            self.dialogue_state.conversation_history = (
                self.dialogue_state.conversation_history[-_MAX_CONVERSATION_HISTORY:]
            )

        # --- Command center update ---
        cc_payload = build_command_center_update(
            self.patient_state, new_facts, self.dialogue_state, now
        )

        # --- Build backward-compatible triage_answers ---
        triage_answers = self.patient_state.known_slots()

        return {
            "question_key": next_q_key,
            "question_text": robot_utterance if next_q_key else None,
            "robot_utterance": robot_utterance,
            "new_facts": new_facts,
            "command_center_payload": cc_payload,
            "triage_complete": triage_complete,
            "triage_answers": triage_answers,
        }

    def get_initial_greeting(self) -> dict[str, Any]:
        """Get the first thing the robot should say when entering triage."""
        return self.process_turn(None, None)
