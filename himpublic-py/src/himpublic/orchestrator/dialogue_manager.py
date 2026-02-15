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
import re
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
    rephrase_used_for: str | None = None  # for rule-based fallback: track if we already rephrased a question


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
# C-alt) Rule-based extraction (fallback when LLM unavailable)
# ---------------------------------------------------------------------------

_BODY_PARTS = {
    "left leg": ["left leg"], "right leg": ["right leg"], "leg": ["leg", "legs"],
    "left arm": ["left arm"], "right arm": ["right arm"], "arm": ["arm", "arms"],
    "head": ["head"], "neck": ["neck"], "chest": ["chest"], "back": ["back"],
    "shoulder": ["shoulder", "shoulders"], "left shoulder": ["left shoulder"], "right shoulder": ["right shoulder"],
    "knee": ["knee", "knees"], "ankle": ["ankle", "ankles"], "wrist": ["wrist", "wrists"],
    "hip": ["hip", "hips"], "hand": ["hand", "hands"], "foot": ["foot", "feet"],
    "abdomen": ["abdomen", "stomach", "belly", "tummy"], "rib": ["rib", "ribs"],
}
_HAZARD_KEYWORDS = {
    "fire": ["fire", "burning", "flames"], "smoke": ["smoke", "smoky", "fumes"],
    "gas": ["gas", "gas leak"], "water": ["water", "flooding", "flooded"],
    "unstable_debris": ["collapsing", "unstable", "falling", "debris falling"],
    "electrical": ["electrical", "wire", "wires", "electr"],
}
_SEVERE_BLEEDING = ["heavy", "lot of blood", "soaking", "pouring", "spurting", "gushing", "won't stop", "can't stop"]
_MODERATE_BLEEDING = ["steady", "steady bleeding", "quite a bit", "some blood", "moderate"]
_MILD_BLEEDING = ["little", "small", "minor", "slow", "just a bit", "trickle"]


def _yes_no(text: str) -> bool | None:
    """Quick yes/no detection with word-boundary awareness."""
    t = text.strip().lower()
    t_words = t.split()
    t_word_set = set(t_words)
    yes_phrases = ("no problem", "i do", "i am", "i can", "i'm not okay", "not really okay")
    no_phrases = ("not really", "i'm not", "im not", "i can't", "i cant", "can't move", "cant move")
    first_word = t_words[0] if t_words else ""
    explicit_yes_start = first_word in ("yes", "yeah", "yep", "y", "ok", "okay", "sure")
    explicit_no_start = first_word in ("no", "nope", "nah", "negative")
    if explicit_yes_start:
        return True
    if explicit_no_start:
        if "no problem" in t:
            return True
        return False
    for phrase in no_phrases:
        if phrase in t:
            return False
    for phrase in yes_phrases:
        if phrase in t:
            return True
    yes_tokens = {"yes", "yeah", "yep", "ok", "okay", "sure", "right", "correct", "true"}
    no_tokens = {"no", "nope", "nah", "negative"}
    if t_word_set & no_tokens:
        return False
    if t_word_set & yes_tokens:
        return True
    return None


def _extract_body_part(text: str) -> str | None:
    t = text.strip().lower()
    for canonical, patterns in sorted(_BODY_PARTS.items(), key=lambda kv: -len(kv[0])):
        for pat in patterns:
            if re.search(rf"\b{re.escape(pat)}\b", t):
                return canonical
    return None


def _extract_pain_score(text: str) -> int | None:
    m = re.search(r"\b([0-9]|10)\s*(?:/?\s*(?:out of\s*)?10)?\b", text.strip())
    if m:
        try:
            v = int(m.group(1))
            if 0 <= v <= 10:
                return v
        except ValueError:
            pass
    return None


def _extract_bleeding_severity(text: str) -> BleedingSeverity:
    t = text.strip().lower()
    for kw in _SEVERE_BLEEDING:
        if kw in t:
            return BleedingSeverity.SEVERE
    for kw in _MILD_BLEEDING:
        if kw in t:
            return BleedingSeverity.MILD
    for kw in _MODERATE_BLEEDING:
        if kw in t:
            return BleedingSeverity.MODERATE
    return BleedingSeverity.UNKNOWN


def _extract_hazards(text: str) -> list[str]:
    t = text.strip().lower()
    found: list[str] = []
    for hazard, keywords in _HAZARD_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                found.append(hazard)
                break
    return found


def parse_victim_utterance(
    text: str,
    patient_state: PatientState,
    current_question_key: str | None = None,
) -> tuple[PatientState, dict[str, Any], dict[str, SlotConfidence]]:
    """
    Rule-based extraction from victim text (used when LLM is unavailable).
    Updates patient_state in-place. Returns (patient_state, extracted_facts, confidences).
    """
    if not text or not text.strip():
        return patient_state, {}, {}
    t = text.strip().lower()
    extracted: dict[str, Any] = {}
    confidences: dict[str, SlotConfidence] = {}

    if current_question_key in ("needs_help", "initial", None):
        yn = _yes_no(text)
        if yn is not None:
            extracted["needs_help"] = yn
            confidences["needs_help"] = SlotConfidence.HIGH
        if any(w in t for w in ("hurt", "injured", "bleeding", "pain", "help", "stuck", "trapped")):
            extracted["needs_help"] = True
            confidences["needs_help"] = SlotConfidence.HIGH

    if patient_state.conscious == Consciousness.UNKNOWN and len(text.split()) >= 2:
            extracted["conscious"] = Consciousness.ALERT
            confidences["conscious"] = SlotConfidence.MEDIUM

    bleeding_mentioned = any(w in t for w in ("bleed", "bleeding", "blood", "hemorrhage", "hemorrhaging"))
    if bleeding_mentioned or current_question_key in ("major_bleeding", "massive_bleeding"):
        yn = _yes_no(text)
        if current_question_key in ("major_bleeding", "massive_bleeding"):
            if yn is True:
                extracted["major_bleeding"] = True
                confidences["major_bleeding"] = SlotConfidence.HIGH
            elif yn is False:
                extracted["major_bleeding"] = False
                confidences["major_bleeding"] = SlotConfidence.HIGH
            elif bleeding_mentioned:
                extracted["major_bleeding"] = True
                confidences["major_bleeding"] = SlotConfidence.MEDIUM
        elif bleeding_mentioned:
            extracted["major_bleeding"] = True
            confidences["major_bleeding"] = SlotConfidence.MEDIUM

    if bleeding_mentioned or current_question_key in ("bleeding_location", "massive_bleeding_where", "injury_location_detail"):
        body_part = _extract_body_part(text)
        if body_part:
            extracted["bleeding_location"] = body_part
            confidences["bleeding_location"] = SlotConfidence.HIGH

    if bleeding_mentioned or current_question_key == "bleeding_severity":
        sev = _extract_bleeding_severity(text)
        if sev != BleedingSeverity.UNKNOWN:
            extracted["bleeding_severity"] = sev
            confidences["bleeding_severity"] = SlotConfidence.MEDIUM

    if current_question_key in ("breathing_distress", "breathing_trouble") or any(w in t for w in ("breath", "breathing", "breathe", "asthma", "wheez", "choking")):
        if current_question_key in ("breathing_distress", "breathing_trouble"):
            yn = _yes_no(text)
            if yn is True:
                extracted["breathing_distress"] = True
                confidences["breathing_distress"] = SlotConfidence.HIGH
            elif yn is False:
                extracted["breathing_distress"] = False
                confidences["breathing_distress"] = SlotConfidence.HIGH
        elif any(w in t for w in ("can't breathe", "hard to breathe", "trouble breathing", "difficulty breathing", "short of breath")):
            extracted["breathing_distress"] = True
            confidences["breathing_distress"] = SlotConfidence.MEDIUM

    if current_question_key == "chest_injury" or any(w in t for w in ("chest", "hole in chest")):
        if current_question_key == "chest_injury":
            yn = _yes_no(text)
            if yn is not None:
                extracted["chest_injury"] = yn
                confidences["chest_injury"] = SlotConfidence.HIGH

    if current_question_key in ("trapped_or_cant_move", "mobility") or any(w in t for w in ("trapped", "stuck", "pinned", "can't move", "cant move")):
        if current_question_key in ("trapped_or_cant_move", "mobility"):
            yn = _yes_no(text)
            if yn is True or any(w in t for w in ("trapped", "stuck", "pinned", "can't move", "cant move")):
                extracted["trapped_or_cant_move"] = True
                confidences["trapped_or_cant_move"] = SlotConfidence.HIGH
            elif yn is False:
                extracted["trapped_or_cant_move"] = False
                confidences["trapped_or_cant_move"] = SlotConfidence.HIGH
        else:
            extracted["trapped_or_cant_move"] = True
            confidences["trapped_or_cant_move"] = SlotConfidence.MEDIUM

    body_part = _extract_body_part(text)
    if body_part and (current_question_key in ("pain", "pain_locations") or "hurt" in t or "pain" in t):
        if body_part not in patient_state.pain_locations:
            patient_state.pain_locations.append(body_part)
            extracted["pain_locations"] = list(patient_state.pain_locations)
            confidences["pain_locations"] = SlotConfidence.HIGH

    pain_score = _extract_pain_score(text)
    if pain_score is not None:
        extracted["pain_score"] = pain_score
        confidences["pain_score"] = SlotConfidence.HIGH

    if current_question_key == "head_injury" or any(w in t for w in ("hit my head", "black out", "blacked out", "concuss")):
        if current_question_key == "head_injury":
            yn = _yes_no(text)
            if yn is not None:
                extracted["head_injury"] = yn
                confidences["head_injury"] = SlotConfidence.HIGH
        else:
            extracted["head_injury"] = True
            confidences["head_injury"] = SlotConfidence.MEDIUM

    if current_question_key == "shock_signs" or any(w in t for w in ("dizzy", "faint", "clammy", "lightheaded")):
        if current_question_key == "shock_signs":
            yn = _yes_no(text)
            if yn is not None:
                extracted["shock_signs"] = yn
                confidences["shock_signs"] = SlotConfidence.HIGH
        else:
            extracted["shock_signs"] = True
            confidences["shock_signs"] = SlotConfidence.MEDIUM

    if current_question_key in ("feeling_cold", "keep_warm"):
        yn = _yes_no(text)
        if yn is not None:
            extracted["feeling_cold"] = yn
            confidences["feeling_cold"] = SlotConfidence.HIGH

    if current_question_key == "consent_photos":
        yn = _yes_no(text)
        if yn is not None:
            extracted["consent_photos"] = yn
            confidences["consent_photos"] = SlotConfidence.HIGH

    hazards = _extract_hazards(text)
    if hazards:
        for h in hazards:
            if h not in patient_state.hazards_present:
                patient_state.hazards_present.append(h)
        extracted["hazards_present"] = list(patient_state.hazards_present)
        confidences["hazards_present"] = SlotConfidence.HIGH

    if current_question_key in ("small_bleeds", "other_wounds") and t and t not in ("no", "nope", "nah", "n"):
            yn = _yes_no(text)
            if yn is not False:
                extracted["other_wounds"] = text.strip()
                confidences["other_wounds"] = SlotConfidence.MEDIUM

    if current_question_key in ("search_location_hint", "location_hint"):
        extracted["location_hint"] = text.strip()
        confidences["location_hint"] = SlotConfidence.MEDIUM

    if current_question_key == "airway_talking":
        yn = _yes_no(text)
        if yn is not None:
            if yn:
                extracted["conscious"] = Consciousness.ALERT
                confidences["conscious"] = SlotConfidence.HIGH
            else:
                extracted["conscious"] = Consciousness.VERBAL
                confidences["conscious"] = SlotConfidence.MEDIUM

    for slot, value in extracted.items():
        conf = confidences.get(slot, SlotConfidence.MEDIUM)
        if hasattr(patient_state, slot) and slot not in ("pain_locations", "hazards_present"):
            patient_state.set_slot(slot, value, conf)

    if text.strip():
        if patient_state.notes_freeform:
            patient_state.notes_freeform += f" | {text.strip()}"
        else:
            patient_state.notes_freeform = text.strip()

    return patient_state, extracted, confidences


# ---------------------------------------------------------------------------
# C) Question bank and next-question selection (for rule-based fallback)
# ---------------------------------------------------------------------------

@dataclass
class QuestionDef:
    """A triage question definition (used when LLM is unavailable)."""
    key: str
    text: str
    slot_checked: str
    priority: int
    prerequisite_slot: str | None = None
    prerequisite_value: Any = None


QUESTION_BANK: list[QuestionDef] = [
    QuestionDef("needs_help", "Can you hear me? Do you need help?", "needs_help", 1),
    QuestionDef("trapped_or_cant_move", "Are you pinned or trapped by anything? Can you move your arms and legs?", "trapped_or_cant_move", 2),
    QuestionDef("major_bleeding", "Is there any heavy bleeding right now?", "major_bleeding", 3),
    QuestionDef("bleeding_location", "Where is the bleeding?", "bleeding_location", 3, "major_bleeding", True),
    QuestionDef("breathing_distress", "Are you having trouble breathing?", "breathing_distress", 4),
    QuestionDef("chest_injury", "Any injury or pain in your chest?", "chest_injury", 4),
    QuestionDef("pain", "Where does it hurt most? Rate your pain from 0 to 10 if you can.", "pain_score", 5),
    QuestionDef("consent_photos", "Is it okay if I take a few photos for the medics?", "consent_photos", 6),
]

_REPHRASE: dict[str, str] = {
    "needs_help": "I'm here to help. Are you injured?",
    "trapped_or_cant_move": "Are you pinned or stuck? Can you move?",
    "major_bleeding": "Do you see any heavy bleeding?",
    "bleeding_location": "Where is the bleeding?",
    "breathing_distress": "How is your breathing?",
    "chest_injury": "Any wound or pain in your chest?",
    "pain": "Where does it hurt? Pain level 0 to 10?",
    "consent_photos": "Okay to take a few photos for the medics?",
}


def _slot_is_unknown(patient_state: PatientState, slot_name: str) -> bool:
    val = getattr(patient_state, slot_name, None)
    if val is None:
        return True
    if isinstance(val, Enum) and val.value == "unknown":
        return True
    if isinstance(val, list) and not val:
        return True
    if isinstance(val, str) and not val:
        return True
    return False


def _prerequisite_met(q: QuestionDef, patient_state: PatientState) -> bool:
    if q.prerequisite_slot is None:
        return True
    val = getattr(patient_state, q.prerequisite_slot, None)
    if isinstance(val, Enum):
        return val.value == q.prerequisite_value
    return val == q.prerequisite_value


def choose_next_question(
    patient_state: PatientState,
    dialogue_state: DialogueState,
    now: float | None = None,
) -> tuple[str | None, str | None]:
    """Choose next question by priority and prerequisites (used in rule-based fallback). Returns (question_key, question_text) or (None, None)."""
    if now is None:
        now = time.monotonic()
    candidates: list[QuestionDef] = []
    for q in QUESTION_BANK:
        if not _slot_is_unknown(patient_state, q.slot_checked):
            conf = patient_state.get_confidence(q.slot_checked)
            if conf in (SlotConfidence.HIGH, SlotConfidence.MEDIUM):
                continue
        if not _prerequisite_met(q, patient_state):
            continue
        if q.key in dialogue_state.asked_question_turns:
                continue
        candidates.append(q)
    if not candidates:
        return None, None
    candidates.sort(key=lambda q: q.priority)
    chosen = candidates[0]
    question_text = chosen.text
    if chosen.key == dialogue_state.last_question_key:
        if getattr(dialogue_state, "rephrase_used_for", None) == chosen.key:
            if len(candidates) > 1:
                chosen = candidates[1]
                question_text = chosen.text
            else:
                return None, None
        elif chosen.key in _REPHRASE:
            question_text = _REPHRASE[chosen.key]
            dialogue_state.rephrase_used_for = chosen.key
    return chosen.key, question_text


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
            # Fallback: rule-based extraction + priority question bank (your original flow)
            logger.warning("LLM unavailable; using rule-based triage (extraction + QUESTION_BANK).")
            if victim_text and victim_text.strip():
                _, new_facts, _ = parse_victim_utterance(
                    victim_text.strip(),
                    self.patient_state,
                    current_question_key=self.dialogue_state.last_question_key,
                )
            else:
                new_facts = {}
            next_q_key, question_text = choose_next_question(
                self.patient_state, self.dialogue_state, now,
            )
            if next_q_key and question_text:
                robot_utterance = question_text
                triage_complete = False
            else:
                robot_utterance = "Thank you. I will now do a visual scan and send images to the medics."
                next_q_key = None
                triage_complete = True

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
