"""Medical chatbot: Wizard-of-Oz interview and evidence-based triage output."""

from __future__ import annotations

import time
from typing import Callable

from himpublic.reporting.types import (
    QAItem,
    QAAnswer,
    MedicalChatbotSection,
    InjuryFinding,
    VictimSummary,
)
from .question_policy import QuestionPolicy, get_default_questions
from .triage_rules import triage_from_qa_and_findings, TriageResult


def terminal_input(prompt: str) -> str:
    """Default: read one line from stdin."""
    return input(prompt).strip()


class MedicalChatbot:
    """Runs clarifying questions (WoZ typed answers) and produces triage section."""

    def __init__(self, policy: QuestionPolicy | None = None):
        self.policy = policy or QuestionPolicy(max_questions=5)

    def run_interview(
        self,
        input_fn: Callable[[str], str] = terminal_input,
        victim: VictimSummary | None = None,
        injuries: list[InjuryFinding] | None = None,
        questions_already_asked: list[str] | None = None,
    ) -> tuple[list[QAItem], list[QAAnswer]]:
        """Ask up to N questions; return questions_asked and answers (with timestamps)."""
        questions_asked: list[QAItem] = []
        answers: list[QAAnswer] = []
        to_ask = self.policy.choose(
            victim=victim,
            injuries=injuries or [],
            questions_already_asked=questions_already_asked or [],
        )
        for q in to_ask:
            t = time.time()
            questions_asked.append(QAItem(question=q, timestamp=t))
            a = input_fn(f"  Q: {q}\n  A: ")
            answers.append(QAAnswer(answer=a or "(no response)", timestamp=time.time()))
        return questions_asked, answers

    def produce_section(
        self,
        questions_asked: list[QAItem],
        answers: list[QAAnswer],
        injuries: list[InjuryFinding] | None = None,
    ) -> MedicalChatbotSection:
        """Build MedicalChatbotSection: summary, triage_priority, triage_rationale, overall_confidence."""
        injuries = injuries or []
        result: TriageResult = triage_from_qa_and_findings(
            questions_asked=questions_asked,
            answers=answers,
            injuries=injuries,
        )
        summary = _summary_paragraph(questions_asked, answers, result)
        return MedicalChatbotSection(
            questions_asked=questions_asked,
            answers=answers,
            chatbot_summary=summary,
            triage_priority=result.priority,
            triage_rationale=result.rationale,
            overall_confidence=result.confidence,
        )


def _summary_paragraph(
    questions_asked: list[QAItem],
    answers: list[QAAnswer],
    result: TriageResult,
) -> str:
    """Human-readable summary with uncertainty language when unknown."""
    parts = [result.summary]
    if result.confidence < 0.6:
        parts.append(" Confidence is limited; more assessment may be needed.")
    if result.priority == "UNKNOWN":
        parts.append(" Uncertainty in triage due to insufficient information.")
    return "".join(parts)
