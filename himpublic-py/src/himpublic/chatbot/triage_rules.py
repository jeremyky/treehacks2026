"""Rule-based triage: RED/YELLOW/GREEN/BLACK/UNKNOWN from QA answers + injury findings."""

from __future__ import annotations

from dataclasses import dataclass

from himpublic.reporting.types import InjuryFinding, MedicalChatbotSection, QAItem, QAAnswer, TriageRationaleItem


@dataclass
class TriageResult:
    priority: str  # RED|YELLOW|GREEN|BLACK|UNKNOWN
    summary: str
    rationale: list[TriageRationaleItem]
    confidence: float


def _answers_lower(answers: list[QAAnswer]) -> list[str]:
    return [a.answer.strip().lower() for a in answers]


def _has_positive(answers: list[QAAnswer], keywords: list[str]) -> bool:
    low = _answers_lower(answers)
    for a in low:
        for k in keywords:
            if k in a and "no" not in a.split(k)[0].split()[-1:]:
                return True
    return False


def _has_negative(answers: list[QAAnswer], keywords: list[str]) -> bool:
    low = _answers_lower(answers)
    for a in low:
        for k in keywords:
            if k in a:
                return True
    return False


def triage_from_qa_and_findings(
    questions_asked: list[QAItem],
    answers: list[QAAnswer],
    injuries: list[InjuryFinding] | None = None,
) -> TriageResult:
    """
    Evidence-based triage. No hallucinations: rationale only references observed findings or answers.
    """
    injuries = injuries or []
    rationale: list[TriageRationaleItem] = []
    priority = "UNKNOWN"
    confidence = 0.0

    # Build answer text for summary
    qa_pairs = []
    for i, q in enumerate(questions_asked):
        a = answers[i].answer if i < len(answers) else "(no response)"
        qa_pairs.append((q.question, a))

    # RED: unconscious, severe bleeding, labored breathing, shock
    if _has_positive(answers, ["no", "can't", "cannot"]) and any("respond" in q.question.lower() for q in questions_asked):
        idx = next((i for i, q in enumerate(questions_asked) if "respond" in q.question.lower()), None)
        if idx is not None and idx < len(answers) and "no" in answers[idx].answer.lower():
            priority = "RED"
            rationale.append(TriageRationaleItem(claim="Victim does not respond to voice.", evidence="Answer to 'Can you respond?': no."))
            confidence = 0.8

    breath_idx = next((i for i, q in enumerate(questions_asked) if "breath" in q.question.lower()), None)
    if not rationale and breath_idx is not None and breath_idx < len(answers):
        a = answers[breath_idx].answer.strip().lower()
        if "yes" in a or "trouble" in a or "labored" in a:
            priority = "RED"
            rationale.append(TriageRationaleItem(claim="Reported trouble breathing.", evidence="Victim indicated breathing difficulty."))
            confidence = 0.75

    for inj in injuries:
        if inj.severity == "severe" and "bleeding" in inj.type.lower():
            if priority != "RED":
                priority = "RED"
                rationale.append(TriageRationaleItem(claim="Severe bleeding observed.", evidence=f"Injury finding: {inj.type} {inj.body_region} severity={inj.severity}."))
            confidence = max(confidence, inj.confidence)

    # YELLOW: moderate bleeding, suspected fracture, limited mobility
    if priority == "UNKNOWN":
        for inj in injuries:
            if inj.severity == "moderate" or "fracture" in inj.type.lower():
                priority = "YELLOW"
                rationale.append(TriageRationaleItem(claim=f"Moderate or fracture indicator: {inj.type}.", evidence=f"Injury: {inj.body_region} severity={inj.severity}."))
                confidence = max(confidence, inj.confidence * 0.9)
        move_idx = next((i for i, q in enumerate(questions_asked) if "move" in q.question.lower()), None)
        if move_idx is not None and move_idx < len(answers):
            a = answers[move_idx].answer.strip().lower()
            if "no" in a or "can't" in a or "cannot" in a or "limited" in a:
                priority = "YELLOW"
                rationale.append(TriageRationaleItem(claim="Limited mobility reported.", evidence="Victim indicated limited movement of arms/legs."))
                confidence = max(confidence, 0.7)

    # GREEN: minor, stable
    if priority == "UNKNOWN" and injuries:
        if all(inj.severity == "minor" for inj in injuries) and len(injuries) <= 2:
            priority = "GREEN"
            rationale.append(TriageRationaleItem(claim="Minor injuries only.", evidence=f"Findings: {len(injuries)} minor injury/ies."))
            confidence = 0.7
    if priority == "UNKNOWN" and answers and not injuries:
        if _has_positive(answers, ["yes"]) and not _has_positive(answers, ["trouble", "bleeding", "dizzy", "hurt"]):
            priority = "GREEN"
            rationale.append(TriageRationaleItem(claim="Responsive and no critical symptoms reported.", evidence="QA answers indicate responsive, no severe complaints."))
            confidence = 0.6

    # BLACK: explicit (e.g. no signs of life) - we don't infer from text
    # Leave as UNKNOWN if nothing matched
    if priority == "UNKNOWN":
        rationale.append(TriageRationaleItem(claim="Insufficient information for triage.", evidence="No clear RED/YELLOW/GREEN indicators from findings or answers."))
        confidence = 0.3

    summary_parts = [f"Triage priority: {priority}."]
    for r in rationale:
        summary_parts.append(f" {r.claim} ({r.evidence})")
    summary = "; ".join(summary_parts)

    return TriageResult(priority=priority, summary=summary, rationale=rationale, confidence=confidence)
