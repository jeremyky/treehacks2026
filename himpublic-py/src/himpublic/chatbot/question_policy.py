"""Question policy: choose up to N questions based on what's missing/uncertain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from himpublic.reporting.types import InjuryFinding, VictimSummary, QAItem


@dataclass
class QuestionPolicy:
    """Select questions to ask based on current report state."""

    max_questions: int = 5
    default_questions: list[str] = None

    def __post_init__(self) -> None:
        if self.default_questions is None:
            self.default_questions = get_default_questions()

    def choose(
        self,
        victim: VictimSummary | None = None,
        injuries: list[InjuryFinding] | None = None,
        questions_already_asked: list[str] | None = None,
    ) -> list[str]:
        """Return ordered list of questions to ask (up to max_questions)."""
        asked = set((questions_already_asked or []))
        candidates: list[str] = []
        for q in self.default_questions:
            if q in asked:
                continue
            candidates.append(q)
            if len(candidates) >= self.max_questions:
                break
        return candidates


def get_default_questions() -> list[str]:
    """Default clarifying questions for triage."""
    return [
        "Can you respond? Say yes or no.",
        "Are you having trouble breathing?",
        "Where does it hurt most?",
        "Are you bleeding heavily?",
        "Can you move your arms and legs?",
        "Do you feel dizzy or faint?",
    ]
