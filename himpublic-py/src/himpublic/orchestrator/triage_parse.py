"""
Parse triage answers: yes/no, pain 0-10, free text.
"""

from __future__ import annotations

import re


def parse_yesno(text: str | None) -> bool | None:
    """
    Simple yes/no detection. Returns True for yes, False for no, None if unclear.
    """
    if not text or not isinstance(text, str):
        return None
    t = text.strip().lower()
    if not t:
        return None
    yes_tokens = ("yes", "yeah", "yep", "y", "ok", "okay", "sure", "please", "do", "correct", "true")
    no_tokens = ("no", "nope", "n", "nah", "don't", "dont", "negative", "false")
    if any(t.startswith(w) or w in t.split() for w in yes_tokens):
        if any(w in t.split() for w in no_tokens) and "no" in t:
            return False
        return True
    if any(t.startswith(w) or w in t.split() for w in no_tokens):
        return False
    return None


def parse_pain_score(text: str | None) -> int | None:
    """
    Extract a number 0-10 from text. Returns None if not found.
    """
    if not text or not isinstance(text, str):
        return None
    # Match "7", "7/10", "pain is 6", "about 8"
    m = re.search(r"\b([0-9]|10)\s*(?:/?\s*10)?\b", text.strip())
    if m:
        try:
            v = int(m.group(1))
            if 0 <= v <= 10:
                return v
        except ValueError:
            pass
    return None


def parse_for_step(text: str | None, expected_type: str, key: str) -> str | bool | int | None:
    """
    Parse text for a given step. Returns value to store in triage_answers.
    - yesno -> bool | None
    - scale_0_10 -> int | None (and store raw text for location)
    - free_text -> str (verbatim, stripped)
    """
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    if expected_type == "yesno":
        return parse_yesno(text)
    if expected_type == "scale_0_10":
        return parse_pain_score(text)
    # free_text: store verbatim
    return text if text else None
