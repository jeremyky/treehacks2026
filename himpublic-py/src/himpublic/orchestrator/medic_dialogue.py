"""
Medic-style dialogue helpers for assist_communicate triage.
Short, clear phrases for TTS. No LLM; deterministic.
"""

from __future__ import annotations

import re
from typing import Any

# Body part keywords that trigger a follow-up question
BODY_PART_KEYWORDS = (
    "leg", "legs", "arm", "arms", "shoulder", "shoulders",
    "head", "neck", "chest", "back", "knee", "knees",
    "ankle", "wrist", "hip", "hand", "hands", "foot", "feet",
)
# Normalize: map variants to a canonical label for summary
BODY_PART_LABELS: dict[str, str] = {
    "leg": "leg", "legs": "leg",
    "arm": "arm", "arms": "arm",
    "shoulder": "shoulder", "shoulders": "shoulder",
    "head": "head", "neck": "neck", "chest": "chest", "back": "back",
    "knee": "knee", "knees": "knee",
    "ankle": "ankle", "wrist": "wrist", "hip": "hip",
    "hand": "hand", "hands": "hand", "foot": "foot", "feet": "foot",
}


def summarize_answer(question_key: str, answer_text: str) -> str:
    """
    Produce a short phrase summarizing the answer for acknowledgement.
    E.g. "leg" in answer -> "Leg issue noted."; yes/no -> "Noted."
    """
    if not answer_text or not isinstance(answer_text, str):
        return "Noted."
    text = answer_text.strip().lower()
    if not text:
        return "Noted."
    # Key-based summaries for MARCH-style prompts (keep short)
    if question_key in ("massive_bleeding", "massive_bleeding_where"):
        return "Bleeding status noted."
    if question_key in ("airway_talking",):
        return "Airway status noted."
    if question_key in ("breathing_trouble", "chest_injury"):
        return "Breathing status noted."
    if question_key in ("shock_signs",):
        return "Circulation status noted."
    if question_key in ("head_injury",):
        return "Head injury status noted."
    if question_key in ("keep_warm",):
        return "Cold exposure noted."

    # Body part mention (general fallback)
    for word in BODY_PART_KEYWORDS:
        if word in text.split() or re.search(rf"\b{re.escape(word)}s?\b", text):
            label = BODY_PART_LABELS.get(word, word)
            return f"{label.capitalize()} issue noted."
    # Yes/no style
    if any(w in text for w in ("yes", "yeah", "yep", "ok", "okay")):
        return "Noted."
    if any(w in text for w in ("no", "nope", "nah")):
        return "Noted."
    # Pain number
    if re.search(r"\b([0-9]|10)\s*(?:/?\s*10)?\b", text):
        return "Pain level noted."
    return "Noted."


def ack_sentence(summary_phrase: str) -> str:
    """Full acknowledgement: summary + 'Sent to the command center.'"""
    if not summary_phrase or summary_phrase.strip() == "Noted.":
        return "Understood. Sent to the command center."
    return f"Understood. {summary_phrase} Sent to the command center."


def next_question_intro() -> str | None:
    """Optional short bridging line before next triage question. Keep short for TTS."""
    return None  # Can be "Next question." or similar if desired


def detect_body_part(answer_text: str) -> str | None:
    """If answer mentions a body part, return the canonical label; else None."""
    if not answer_text or not isinstance(answer_text, str):
        return None
    text = answer_text.strip().lower()
    for word in BODY_PART_KEYWORDS:
        if re.search(rf"\b{re.escape(word)}s?\b", text):
            return BODY_PART_LABELS.get(word, word)
    return None


def get_body_part_followup_question(answer_text: str) -> str | None:
    """
    If answer mentions a body part, return a short follow-up question.
    Otherwise return None. One follow-up only: side + bleeding/pain.
    """
    if detect_body_part(answer_text) is None:
        return None
    # Single deterministic follow-up
    return "Which side, left or right? Is there bleeding or mainly pain?"


def should_insert_body_part_followup(question_key: str, answer_text: str) -> bool:
    """True if we should ask the body-part follow-up before continuing triage."""
    if not answer_text or question_key == "injury_location_detail":
        return False
    # Only insert followups on questions where body location details are useful.
    allowed_keys = {
        "massive_bleeding_where",
        "small_bleeds",
        "pain",
        "mobility",
        "initial",
    }
    if question_key and question_key not in allowed_keys:
        return False
    return get_body_part_followup_question(answer_text) is not None
