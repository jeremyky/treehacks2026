"""
QuestionPlanner — maps CV findings to targeted triage questions.

Rules-based: each finding_type has a bank of questions.
A tiny state machine prevents repeating questions already asked.

Usage::

    planner = QuestionPlanner()
    questions = planner.next_questions(findings, max_questions=4)
    # ...patient answers...
    planner.mark_answered("bleed_severity", answer_text)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .schemas import Finding, FindingType

logger = logging.getLogger(__name__)


@dataclass
class TriageQuestion:
    """One question to ask the victim."""
    id: str
    text: str
    finding_ref: int = -1          # index into findings list (or -1 for generic)
    category: str = ""             # e.g. "bleeding", "burn"
    priority: int = 0              # lower = ask first


# ── Question bank per finding type ───────────────────────────────────────

_QUESTION_BANK: dict[FindingType, list[dict[str, Any]]] = {
    "suspected_bleeding": [
        {"id": "bleed_severity", "text": "I see possible bleeding on your {body_region}. Is the bleeding heavy, moderate, or light?", "priority": 0},
        {"id": "bleed_dizzy", "text": "Are you feeling dizzy or faint?", "priority": 1},
        {"id": "bleed_pressure", "text": "Can you apply pressure to the area?", "priority": 2},
    ],
    "suspected_burn": [
        {"id": "burn_blister", "text": "Is the burn blistering or is the skin broken?", "priority": 0},
        {"id": "burn_pain", "text": "Is the pain severe?", "priority": 1},
        {"id": "burn_source", "text": "What caused the burn?", "priority": 2},
    ],
    "suspected_bruise": [
        {"id": "bruise_pain", "text": "Do you have strong pain there or limited movement?", "priority": 0},
        {"id": "bruise_swelling", "text": "Is there any swelling around that area?", "priority": 1},
    ],
    "suspected_wound": [
        {"id": "wound_depth", "text": "How deep does the wound appear to be?", "priority": 0},
        {"id": "wound_bleeding", "text": "Is the wound still bleeding?", "priority": 1},
        {"id": "wound_cause", "text": "What caused this wound?", "priority": 2},
    ],
    "suspected_immobility": [
        {"id": "immobility_fingers", "text": "Can you move your fingers and toes?", "priority": 0},
        {"id": "immobility_breathing", "text": "Do you have trouble breathing?", "priority": 1},
        {"id": "immobility_pain", "text": "Where exactly do you feel pain when you try to move?", "priority": 2},
    ],
    "unknown": [
        {"id": "general_pain", "text": "Can you tell me where it hurts the most?", "priority": 0},
        {"id": "general_breathing", "text": "Are you having any difficulty breathing?", "priority": 1},
    ],
}

# Generic questions always available
_GENERIC_QUESTIONS: list[dict[str, Any]] = [
    {"id": "gen_name", "text": "What is your name?", "priority": -1},
    {"id": "gen_allergies", "text": "Do you have any known allergies or medical conditions?", "priority": 5},
    {"id": "gen_meds", "text": "Are you currently taking any medications?", "priority": 6},
]


class QuestionPlanner:
    """
    Stateful question planner that maps findings → ordered questions.

    Tracks which questions have been asked / answered to avoid repetition.
    """

    def __init__(self, include_generic: bool = True) -> None:
        self._asked: set[str] = set()
        self._answers: dict[str, str] = {}
        self._include_generic = include_generic

    # ── public API ────────────────────────────────────────────

    def next_questions(
        self,
        findings: list[Finding],
        max_questions: int = 4,
        spoken_body_region: str | None = None,
    ) -> list[TriageQuestion]:
        """
        Given current findings, return the next batch of questions to ask.

        If spoken_body_region is set (e.g. from "Where are you hurt?" -> "my knee"),
        that is used for {body_region} in question text instead of CV/pose inference.
        """
        candidates: list[TriageQuestion] = []
        region_override = (spoken_body_region or "").strip() or None

        # Finding-specific questions
        for k, finding in enumerate(findings):
            bank = _QUESTION_BANK.get(finding.finding_type, _QUESTION_BANK["unknown"])
            for q in bank:
                qid = q["id"]
                if qid in self._asked:
                    continue
                body_region = region_override if region_override else finding.body_region
                text = q["text"].format(body_region=body_region or "there")
                candidates.append(TriageQuestion(
                    id=qid,
                    text=text,
                    finding_ref=k,
                    category=finding.finding_type.replace("suspected_", ""),
                    priority=q["priority"],
                ))

        # Generic questions
        if self._include_generic:
            for q in _GENERIC_QUESTIONS:
                qid = q["id"]
                if qid in self._asked:
                    continue
                candidates.append(TriageQuestion(
                    id=qid,
                    text=q["text"],
                    finding_ref=-1,
                    category="general",
                    priority=q["priority"],
                ))

        # Sort by priority, then deduplicate by id
        candidates.sort(key=lambda q: q.priority)
        seen: set[str] = set()
        unique: list[TriageQuestion] = []
        for q in candidates:
            if q.id not in seen:
                seen.add(q.id)
                unique.append(q)

        chosen = unique[:max_questions]
        logger.info(
            "QuestionPlanner: %d candidate(s), returning %d question(s)",
            len(unique), len(chosen),
        )
        return chosen

    def mark_asked(self, question_id: str) -> None:
        """Record that a question has been asked (even if no answer yet)."""
        self._asked.add(question_id)

    def mark_answered(self, question_id: str, answer: str) -> None:
        """Record both that the question was asked and what the victim said."""
        self._asked.add(question_id)
        self._answers[question_id] = answer

    def get_answers(self) -> dict[str, str]:
        """Return all answers collected so far."""
        return dict(self._answers)

    def reset(self) -> None:
        """Clear all state (new victim)."""
        self._asked.clear()
        self._answers.clear()

    @property
    def asked_count(self) -> int:
        return len(self._asked)

    @property
    def answered_count(self) -> int:
        return len(self._answers)
