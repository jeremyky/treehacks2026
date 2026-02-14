"""
Slot-based dialogue manager for medical triage Q&A.

Replaces the linear triage script with a context-aware system that:
- Extracts structured facts ("slots") from victim utterances.
- Maintains patient state across turns.
- Chooses the next best question based on missing high-priority slots.
- Prevents repeated questions and duplicate command-center messages.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
# A) Dialogue state: conversation tracking
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
    consecutive_unrelated_responses: int = 0
    last_ack_text: str = ""  # to avoid repeating ack
    rephrase_used_for: str | None = None  # track if we already rephrased a question


# ---------------------------------------------------------------------------
# B) NLU extraction: parse victim utterances into slot updates
# ---------------------------------------------------------------------------

# Body-part patterns
_BODY_PARTS = {
    "left leg": ["left leg"],
    "right leg": ["right leg"],
    "leg": ["leg", "legs"],
    "left arm": ["left arm"],
    "right arm": ["right arm"],
    "arm": ["arm", "arms"],
    "head": ["head"],
    "neck": ["neck"],
    "chest": ["chest"],
    "back": ["back"],
    "shoulder": ["shoulder", "shoulders"],
    "left shoulder": ["left shoulder"],
    "right shoulder": ["right shoulder"],
    "knee": ["knee", "knees"],
    "ankle": ["ankle", "ankles"],
    "wrist": ["wrist", "wrists"],
    "hip": ["hip", "hips"],
    "hand": ["hand", "hands"],
    "foot": ["foot", "feet"],
    "abdomen": ["abdomen", "stomach", "belly", "tummy"],
    "rib": ["rib", "ribs"],
}

# Hazard keywords
_HAZARD_KEYWORDS = {
    "fire": ["fire", "burning", "flames"],
    "smoke": ["smoke", "smoky", "fumes"],
    "gas": ["gas", "gas leak"],
    "water": ["water", "flooding", "flooded"],
    "unstable_debris": ["collapsing", "unstable", "falling", "debris falling"],
    "electrical": ["electrical", "wire", "wires", "electr"],
}

# Bleeding severity heuristics
_SEVERE_BLEEDING = ["heavy", "lot of blood", "soaking", "pouring", "spurting", "gushing", "won't stop", "can't stop"]
_MODERATE_BLEEDING = ["steady", "steady bleeding", "quite a bit", "some blood", "moderate"]
_MILD_BLEEDING = ["little", "small", "minor", "slow", "just a bit", "trickle"]


def _yes_no(text: str) -> bool | None:
    """Quick yes/no detection with word-boundary awareness."""
    t = text.strip().lower()
    t_words = t.split()
    t_word_set = set(t_words)

    # Multi-word yes/no phrases (check first for specificity)
    yes_phrases = ("no problem", "i do", "i am", "i can", "i'm not okay", "not really okay")
    no_phrases = ("not really", "i'm not", "im not", "i can't", "i cant", "can't move", "cant move")

    # Check if the response STARTS with an explicit yes or no
    first_word = t_words[0] if t_words else ""
    explicit_yes_start = first_word in ("yes", "yeah", "yep", "y", "ok", "okay", "sure")
    explicit_no_start = first_word in ("no", "nope", "nah", "negative")

    # If starts with explicit yes/no, that's the answer regardless of what follows
    if explicit_yes_start:
        return True
    if explicit_no_start:
        if "no problem" in t:
            return True
        return False

    # Check multi-word no phrases
    for phrase in no_phrases:
        if phrase in t:
            return False

    # Check multi-word yes phrases
    for phrase in yes_phrases:
        if phrase in t:
            return True

    # Single-word matching (use word boundaries, NOT substring matching)
    yes_tokens = {"yes", "yeah", "yep", "ok", "okay", "sure", "right", "correct", "true"}
    no_tokens = {"no", "nope", "nah", "negative"}

    if t_word_set & no_tokens:
        return False
    if t_word_set & yes_tokens:
        return True

    return None


def _extract_body_part(text: str) -> str | None:
    """Extract the most specific body-part mention from text."""
    t = text.strip().lower()
    # Try more-specific (2-word) patterns first
    for canonical, patterns in sorted(_BODY_PARTS.items(), key=lambda kv: -len(kv[0])):
        for pat in patterns:
            if re.search(rf"\b{re.escape(pat)}\b", t):
                return canonical
    return None


def _extract_pain_score(text: str) -> int | None:
    """Extract pain score 0-10."""
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
    """Estimate bleeding severity from text."""
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
    """Extract mentioned hazards."""
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
    Extract structured facts from a victim's utterance.

    Args:
        text: The victim's spoken text (transcript).
        patient_state: Current patient state (will be updated in-place).
        current_question_key: The question we just asked (helps context).

    Returns:
        (updated_patient_state, extracted_facts, confidences)
        extracted_facts: dict of slot_name -> extracted_value (only NEW facts)
        confidences: dict of slot_name -> SlotConfidence
    """
    if not text or not text.strip():
        return patient_state, {}, {}

    t = text.strip().lower()
    extracted: dict[str, Any] = {}
    confidences: dict[str, SlotConfidence] = {}

    # --- Contextual extraction based on what we asked ---

    # Needs help
    if current_question_key in ("needs_help", "initial", None):
        yn = _yes_no(text)
        if yn is not None:
            extracted["needs_help"] = yn
            confidences["needs_help"] = SlotConfidence.HIGH
        # Even without explicit yes/no, if they describe injuries, they need help
        if any(w in t for w in ("hurt", "injured", "bleeding", "pain", "help", "stuck", "trapped")):
            extracted["needs_help"] = True
            confidences["needs_help"] = SlotConfidence.HIGH

    # Consciousness: if they're talking coherently, they're at least VERBAL
    if patient_state.conscious == Consciousness.UNKNOWN:
        if len(text.split()) >= 2:
            extracted["conscious"] = Consciousness.ALERT
            confidences["conscious"] = SlotConfidence.MEDIUM

    # Bleeding
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

    # Bleeding location
    if bleeding_mentioned or current_question_key in (
        "bleeding_location", "massive_bleeding_where", "injury_location_detail",
    ):
        body_part = _extract_body_part(text)
        if body_part:
            extracted["bleeding_location"] = body_part
            confidences["bleeding_location"] = SlotConfidence.HIGH

    # Bleeding severity
    if bleeding_mentioned or current_question_key in ("bleeding_severity",):
        sev = _extract_bleeding_severity(text)
        if sev != BleedingSeverity.UNKNOWN:
            extracted["bleeding_severity"] = sev
            confidences["bleeding_severity"] = SlotConfidence.MEDIUM

    # Breathing
    if current_question_key in ("breathing_distress", "breathing_trouble") or \
       any(w in t for w in ("breath", "breathing", "breathe", "asthma", "wheez", "choking")):
        if current_question_key in ("breathing_distress", "breathing_trouble"):
            yn = _yes_no(text)
            if yn is True:
                extracted["breathing_distress"] = True
                confidences["breathing_distress"] = SlotConfidence.HIGH
            elif yn is False:
                extracted["breathing_distress"] = False
                confidences["breathing_distress"] = SlotConfidence.HIGH
        elif any(w in t for w in ("can't breathe", "hard to breathe", "trouble breathing",
                                  "difficulty breathing", "short of breath")):
            extracted["breathing_distress"] = True
            confidences["breathing_distress"] = SlotConfidence.MEDIUM

    # Chest injury
    if current_question_key in ("chest_injury",) or any(w in t for w in ("chest", "hole in chest")):
        if current_question_key == "chest_injury":
            yn = _yes_no(text)
            if yn is not None:
                extracted["chest_injury"] = yn
                confidences["chest_injury"] = SlotConfidence.HIGH

    # Trapped / can't move
    if current_question_key in ("trapped_or_cant_move", "mobility") or \
       any(w in t for w in ("trapped", "stuck", "pinned", "can't move", "cant move")):
        if current_question_key in ("trapped_or_cant_move", "mobility"):
            yn = _yes_no(text)
            if yn is True or any(w in t for w in ("trapped", "stuck", "pinned", "can't move", "cant move")):
                extracted["trapped_or_cant_move"] = True
                confidences["trapped_or_cant_move"] = SlotConfidence.HIGH
            elif yn is False:
                extracted["trapped_or_cant_move"] = False
                confidences["trapped_or_cant_move"] = SlotConfidence.HIGH
        elif any(w in t for w in ("trapped", "stuck", "pinned", "can't move", "cant move")):
            extracted["trapped_or_cant_move"] = True
            confidences["trapped_or_cant_move"] = SlotConfidence.MEDIUM

    # Pain locations + score
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

    # Head injury
    if current_question_key in ("head_injury",) or any(w in t for w in ("hit my head", "black out", "blacked out", "concuss")):
        if current_question_key == "head_injury":
            yn = _yes_no(text)
            if yn is not None:
                extracted["head_injury"] = yn
                confidences["head_injury"] = SlotConfidence.HIGH
        elif any(w in t for w in ("hit my head", "black out", "blacked out", "concuss")):
            extracted["head_injury"] = True
            confidences["head_injury"] = SlotConfidence.MEDIUM

    # Shock signs
    if current_question_key in ("shock_signs",) or any(w in t for w in ("dizzy", "faint", "clammy", "lightheaded")):
        if current_question_key == "shock_signs":
            yn = _yes_no(text)
            if yn is not None:
                extracted["shock_signs"] = yn
                confidences["shock_signs"] = SlotConfidence.HIGH
        elif any(w in t for w in ("dizzy", "faint", "clammy", "lightheaded")):
            extracted["shock_signs"] = True
            confidences["shock_signs"] = SlotConfidence.MEDIUM

    # Feeling cold
    if current_question_key in ("feeling_cold", "keep_warm"):
        yn = _yes_no(text)
        if yn is not None:
            extracted["feeling_cold"] = yn
            confidences["feeling_cold"] = SlotConfidence.HIGH

    # Consent for photos
    if current_question_key in ("consent_photos",):
        yn = _yes_no(text)
        if yn is not None:
            extracted["consent_photos"] = yn
            confidences["consent_photos"] = SlotConfidence.HIGH

    # Hazards (always check, regardless of question)
    hazards = _extract_hazards(text)
    if hazards:
        for h in hazards:
            if h not in patient_state.hazards_present:
                patient_state.hazards_present.append(h)
        extracted["hazards_present"] = list(patient_state.hazards_present)
        confidences["hazards_present"] = SlotConfidence.HIGH

    # Other wounds (free text capture for relevant questions)
    if current_question_key in ("small_bleeds", "other_wounds"):
        if t and t not in ("no", "nope", "nah", "n"):
            yn = _yes_no(text)
            if yn is not False:
                extracted["other_wounds"] = text.strip()
                confidences["other_wounds"] = SlotConfidence.MEDIUM

    # Location hint
    if current_question_key in ("search_location_hint", "location_hint"):
        extracted["location_hint"] = text.strip()
        confidences["location_hint"] = SlotConfidence.MEDIUM

    # Airway: if they can talk clearly, airway is likely okay
    if current_question_key in ("airway_talking",):
        yn = _yes_no(text)
        if yn is not None:
            # "Can you talk to me clearly?" -> Yes means conscious=ALERT
            if yn:
                extracted["conscious"] = Consciousness.ALERT
                confidences["conscious"] = SlotConfidence.HIGH
            else:
                extracted["conscious"] = Consciousness.VERBAL
                confidences["conscious"] = SlotConfidence.MEDIUM

    # Apply all extracted facts to patient state
    for slot, value in extracted.items():
        conf = confidences.get(slot, SlotConfidence.MEDIUM)
        if hasattr(patient_state, slot) and slot not in ("pain_locations", "hazards_present"):
            patient_state.set_slot(slot, value, conf)

    # Append freeform notes
    if text.strip():
        if patient_state.notes_freeform:
            patient_state.notes_freeform += f" | {text.strip()}"
        else:
            patient_state.notes_freeform = text.strip()

    return patient_state, extracted, confidences


# ---------------------------------------------------------------------------
# C) Question selection: priority-based, context-aware
# ---------------------------------------------------------------------------

@dataclass
class QuestionDef:
    """A triage question definition."""
    key: str
    text: str
    slot_checked: str  # which slot this question fills
    priority: int  # lower = higher priority (asked first)
    # Some questions only apply if a prerequisite slot has a certain value
    prerequisite_slot: str | None = None
    prerequisite_value: Any = None


# Ordered question bank: priority 1 = life threat, priority 5 = documentation
QUESTION_BANK: list[QuestionDef] = [
    # Priority 1: Consciousness / responsiveness
    QuestionDef(
        key="needs_help",
        text="Can you hear me? Are you hurt? Do you need help?",
        slot_checked="needs_help",
        priority=1,
    ),
    # Priority 2: Major bleeding
    QuestionDef(
        key="major_bleeding",
        text="Is there any heavy bleeding right now?",
        slot_checked="major_bleeding",
        priority=2,
    ),
    QuestionDef(
        key="bleeding_location",
        text="Where is the bleeding? Which part of your body?",
        slot_checked="bleeding_location",
        priority=2,
        prerequisite_slot="major_bleeding",
        prerequisite_value=True,
    ),
    QuestionDef(
        key="bleeding_severity",
        text="How heavy is the bleeding? Is it soaking through cloth quickly, or is it slow? If you can, apply firm pressure.",
        slot_checked="bleeding_severity",
        priority=2,
        prerequisite_slot="major_bleeding",
        prerequisite_value=True,
    ),
    # Priority 3: Airway / breathing
    QuestionDef(
        key="airway_talking",
        text="Can you talk to me clearly without difficulty?",
        slot_checked="conscious",
        priority=3,
    ),
    QuestionDef(
        key="breathing_distress",
        text="Are you having any trouble breathing right now?",
        slot_checked="breathing_distress",
        priority=3,
    ),
    QuestionDef(
        key="chest_injury",
        text="Any chest injury, or does it feel like there's a wound on your chest?",
        slot_checked="chest_injury",
        priority=3,
    ),
    # Priority 4: Circulation / shock / mobility
    QuestionDef(
        key="shock_signs",
        text="Do you feel dizzy, faint, or very cold and clammy?",
        slot_checked="shock_signs",
        priority=4,
    ),
    QuestionDef(
        key="trapped_or_cant_move",
        text="Can you move your arms and legs? Are you trapped or pinned by anything?",
        slot_checked="trapped_or_cant_move",
        priority=4,
    ),
    # Priority 4: Head injury
    QuestionDef(
        key="head_injury",
        text="Did you hit your head or lose consciousness at any point?",
        slot_checked="head_injury",
        priority=4,
    ),
    # Priority 5: Hazards
    QuestionDef(
        key="hazards",
        text="Is there any fire, smoke, gas, or unstable debris near you?",
        slot_checked="hazards_present",
        priority=5,
    ),
    # Priority 5: Additional wounds, pain
    QuestionDef(
        key="other_wounds",
        text="Any other bleeding or wounds I should know about?",
        slot_checked="other_wounds",
        priority=5,
    ),
    QuestionDef(
        key="pain",
        text="Where does it hurt most? Can you rate your pain from 0 to 10?",
        slot_checked="pain_score",
        priority=5,
    ),
    QuestionDef(
        key="feeling_cold",
        text="Are you feeling very cold right now?",
        slot_checked="feeling_cold",
        priority=6,
    ),
    # Priority 7: Documentation / consent
    QuestionDef(
        key="consent_photos",
        text="Is it okay if I take some photos to help the medics assess your condition?",
        slot_checked="consent_photos",
        priority=7,
    ),
]

# Build lookup
_QUESTION_BY_KEY: dict[str, QuestionDef] = {q.key: q for q in QUESTION_BANK}

# Rephrased versions of questions (used when repeating)
_REPHRASE: dict[str, str] = {
    "needs_help": "I'm here to help. Can you tell me if you're injured?",
    "major_bleeding": "I need to check—do you see any blood or heavy bleeding on your body?",
    "bleeding_location": "Can you point to or describe where the bleeding is coming from?",
    "bleeding_severity": "Is the bleeding fast and heavy, or more of a slow ooze? Try pressing firmly on it if you can.",
    "breathing_distress": "How is your breathing? Any shortness of breath or difficulty?",
    "chest_injury": "Is there any wound or pain in your chest area?",
    "shock_signs": "Are you feeling lightheaded, dizzy, or unusually cold?",
    "trapped_or_cant_move": "Are you able to move freely, or is something pinning you down?",
    "head_injury": "Did you hit your head? Have you blacked out at all?",
    "consent_photos": "I'd like to take a few photos for the medical team. Is that alright?",
}


def _slot_is_unknown(patient_state: PatientState, slot_name: str) -> bool:
    """Check if a slot is still unknown/unfilled."""
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
    """Check if a question's prerequisite is satisfied."""
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
    """
    Choose the next best question based on missing high-priority slots.

    Returns:
        (question_key, question_text) or (None, None) if all slots are filled.
    """
    if now is None:
        now = time.monotonic()

    recency_turns = 3  # don't re-ask within this many turns
    recency_seconds = 30.0

    candidates: list[QuestionDef] = []

    for q in QUESTION_BANK:
        # Skip if slot is already known (with sufficient confidence)
        if not _slot_is_unknown(patient_state, q.slot_checked):
            conf = patient_state.get_confidence(q.slot_checked)
            if conf in (SlotConfidence.HIGH, SlotConfidence.MEDIUM):
                continue  # Already have a good answer

        # Skip if prerequisite not met
        if not _prerequisite_met(q, patient_state):
            continue

        # Check recency: was this asked too recently?
        if q.key in dialogue_state.asked_question_turns:
            turns_ago = dialogue_state.turn_index - dialogue_state.asked_question_turns[q.key]
            if turns_ago < recency_turns:
                continue
        if q.key in dialogue_state.asked_question_keys:
            time_ago = now - dialogue_state.asked_question_keys[q.key]
            if time_ago < recency_seconds:
                continue

        candidates.append(q)

    if not candidates:
        return None, None

    # Sort by priority (lower = higher priority)
    candidates.sort(key=lambda q: q.priority)
    chosen = candidates[0]

    # --- Repetition guardrail ---
    question_text = chosen.text

    # If this is the same as the last question AND no new info arrived, rephrase or skip
    if chosen.key == dialogue_state.last_question_key:
        if dialogue_state.rephrase_used_for == chosen.key:
            # Already rephrased once; skip to next candidate
            if len(candidates) > 1:
                chosen = candidates[1]
                question_text = chosen.text
            else:
                return None, None  # nothing left to ask
        elif chosen.key in _REPHRASE:
            question_text = _REPHRASE[chosen.key]
            dialogue_state.rephrase_used_for = chosen.key
        # If no rephrase available, use original text (first repeat is okay)

    return chosen.key, question_text


# ---------------------------------------------------------------------------
# E) Command-center update dedup
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
            return None  # never sent before and no new facts → skip
        if (now - dialogue_state.last_update_time) < min_interval_s * 6:
            return None  # sent recently, nothing new → skip

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
        return None  # duplicate — don't send

    dialogue_state.last_command_center_payload_hash = payload_hash
    dialogue_state.last_update_time = now
    return payload


# ---------------------------------------------------------------------------
# F) Robot utterance generation: single concise turn
# ---------------------------------------------------------------------------

def generate_robot_utterance(
    new_facts: dict[str, Any],
    question_key: str | None,
    question_text: str | None,
    patient_state: PatientState,
    dialogue_state: DialogueState,
    sent_update: bool = False,
) -> str:
    """
    Generate a single, concise robot utterance:
    - 1 sentence empathy/ack (only if new facts)
    - 1 sentence stating what was recorded (only if new)
    - 1 next question
    No duplicate confirmations.
    """
    parts: list[str] = []

    # --- Empathy / acknowledgment (only if new facts) ---
    if new_facts:
        ack = _build_ack(new_facts, patient_state)
        if ack and ack != dialogue_state.last_ack_text:
            parts.append(ack)
            dialogue_state.last_ack_text = ack

        # --- What was recorded ---
        if sent_update:
            parts.append("I've updated the medical team.")

    # --- Next question ---
    if question_text:
        parts.append(question_text)

    if not parts:
        return "I'm here with you. Let me know if anything changes."

    return " ".join(parts)


def _build_ack(new_facts: dict[str, Any], patient_state: PatientState) -> str:
    """Build a short acknowledgment sentence based on what was just learned."""
    if not new_facts:
        return ""

    # Prioritize specific acks
    if "bleeding_location" in new_facts:
        loc = new_facts["bleeding_location"]
        if isinstance(loc, str):
            return f"I understand—bleeding from your {loc}."

    if "major_bleeding" in new_facts:
        if new_facts["major_bleeding"]:
            return "Understood, there is active bleeding."
        else:
            return "Good, no major bleeding."

    if "bleeding_severity" in new_facts:
        sev = new_facts["bleeding_severity"]
        sev_str = sev.value if isinstance(sev, Enum) else str(sev)
        return f"Noted—{sev_str} bleeding."

    if "breathing_distress" in new_facts:
        if new_facts["breathing_distress"]:
            return "I hear you're having trouble breathing."
        else:
            return "Good, breathing is okay."

    if "needs_help" in new_facts:
        if new_facts["needs_help"]:
            return "I'm here to help you."
        else:
            return "Alright, glad you're okay."

    if "trapped_or_cant_move" in new_facts:
        if new_facts["trapped_or_cant_move"]:
            return "I understand you're trapped. Help is on the way."
        else:
            return "Good, you can move."

    if "head_injury" in new_facts:
        if new_facts["head_injury"]:
            return "Head injury noted. Try to stay still."

    if "pain_score" in new_facts:
        return f"Pain level {new_facts['pain_score']} noted."

    if "consent_photos" in new_facts:
        if new_facts["consent_photos"]:
            return "Thank you for your consent."
        else:
            return "Understood, no photos."

    # Generic
    return "Understood."


# ---------------------------------------------------------------------------
# Main dialogue manager class
# ---------------------------------------------------------------------------

class TriageDialogueManager:
    """
    Stateful dialogue manager for medical triage.
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
        Process one dialogue turn.

        Args:
            victim_text: What the victim said (None if no response / first turn).
            current_question_key: The question we last asked.
            now: Current time (monotonic).

        Returns:
            dict with keys:
                "question_key": str | None  — next question to ask
                "question_text": str | None — next question text
                "robot_utterance": str       — full robot speech (ack + recorded + question)
                "new_facts": dict            — newly extracted facts
                "command_center_payload": dict | None — payload to send (or None = skip)
                "triage_complete": bool      — True if all questions exhausted
                "triage_answers": dict       — all known patient facts (for backward compat)
        """
        if now is None:
            now = time.monotonic()

        new_facts: dict[str, Any] = {}
        confidences: dict[str, SlotConfidence] = {}

        # --- Parse victim utterance ---
        if victim_text and victim_text.strip():
            self.patient_state, new_facts, confidences = parse_victim_utterance(
                victim_text, self.patient_state, current_question_key
            )
            self.dialogue_state.consecutive_unrelated_responses = 0
            # Check if response is unrelated (no facts extracted for the question we asked)
            if current_question_key and not new_facts:
                self.dialogue_state.consecutive_unrelated_responses += 1
        elif victim_text is not None:
            # Empty response
            pass

        self.dialogue_state.turn_index += 1

        # --- Choose next question ---
        q_key, q_text = choose_next_question(self.patient_state, self.dialogue_state, now)
        triage_complete = q_key is None

        # Record that we're asking this question
        if q_key:
            self.dialogue_state.asked_question_keys[q_key] = now
            self.dialogue_state.asked_question_turns[q_key] = self.dialogue_state.turn_index
            self.dialogue_state.last_question_key = q_key

        # --- Command center update ---
        cc_payload = build_command_center_update(
            self.patient_state, new_facts, self.dialogue_state, now
        )

        # --- Generate robot utterance ---
        utterance = generate_robot_utterance(
            new_facts, q_key, q_text,
            self.patient_state, self.dialogue_state,
            sent_update=cc_payload is not None,
        )

        # --- Build backward-compatible triage_answers ---
        triage_answers = self.patient_state.known_slots()

        return {
            "question_key": q_key,
            "question_text": q_text,
            "robot_utterance": utterance,
            "new_facts": new_facts,
            "command_center_payload": cc_payload,
            "triage_complete": triage_complete,
            "triage_answers": triage_answers,
        }

    def get_initial_greeting(self) -> dict[str, Any]:
        """Get the first thing the robot should say when entering triage."""
        return self.process_turn(None, None)
