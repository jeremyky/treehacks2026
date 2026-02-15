"""
Recovered linear triage runner (v2).

This is the deterministic, step-index-based triage flow that existed before the
ASSIST_COMMUNICATE phase switched to `TriageDialogueManager`.

It is NOT wired into the current policy by default; it is kept as a safe,
importable module so you can compare/restore the old behavior during demos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from himpublic.orchestrator.triage_parse import parse_for_step
from himpublic.orchestrator.triage_script import TriageStep, get_step, is_acknowledge_step, num_steps


@dataclass
class LinearTriageResult:
    """What to do next in a linear triage flow."""

    action: str  # "ask" | "say" | "done"
    say: str | None
    triage_step_index: int
    current_question_key: str | None
    triage_answers_delta: dict[str, Any]


def _should_ask(step: TriageStep, triage_answers: dict[str, Any]) -> bool:
    """Skip conditional followups based on earlier answers."""
    # Only ask "where is the bleeding" if we established major bleeding.
    if step.key == "massive_bleeding_where":
        return bool(triage_answers.get("massive_bleeding") is True)
    return True


def _advance_to_next_question_index(start_index: int, triage_answers: dict[str, Any]) -> int:
    """Skip acknowledge sentinel and conditional steps to find the next askable step."""
    i = max(0, start_index)
    while i < num_steps():
        s = get_step(i)
        if s is None:
            return i
        if isinstance(s, str):
            # sentinel (e.g. "acknowledge")
            return i
        if _should_ask(s, triage_answers):
            return i
        i += 1
    return i


def step_once(
    *,
    triage_step_index: int,
    last_response: str | None,
    current_question_key: str | None,
    triage_answers: dict[str, Any] | None = None,
) -> LinearTriageResult:
    """
    Run ONE update of the linear triage script.

    Inputs are shaped to match `agent.py` conversation state:
    - triage_step_index: index into TRIAGE_STEPS
    - last_response: latest victim utterance (may be None/empty)
    - current_question_key: which key we were collecting an answer for
    - triage_answers: accumulated answers

    Returns what the robot should do next (ASK/SAY/DONE) and state deltas.
    """
    triage_answers = dict(triage_answers or {})
    delta: dict[str, Any] = {}

    # 1) If we have a response to a previously-asked step, parse & store it.
    if last_response and current_question_key:
        # Find the step metadata by key
        step_meta: TriageStep | None = None
        for idx in range(num_steps()):
            s = get_step(idx)
            if isinstance(s, TriageStep) and s.key == current_question_key:
                step_meta = s
                break
        if step_meta is not None:
            parsed = parse_for_step(last_response, step_meta.expected_answer_type, step_meta.key)
            if parsed is not None:
                triage_answers[step_meta.key] = parsed
                delta[step_meta.key] = parsed

    # 2) Decide next step to emit
    i = _advance_to_next_question_index(triage_step_index, triage_answers)
    s = get_step(i)
    if s is None:
        return LinearTriageResult(
            action="done",
            say=None,
            triage_step_index=i,
            current_question_key=None,
            triage_answers_delta=delta,
        )

    # 2a) Acknowledge step (SAY only)
    if is_acknowledge_step(i):
        return LinearTriageResult(
            action="say",
            say="Noted. Sending to command center.",
            triage_step_index=i + 1,
            current_question_key=None,
            triage_answers_delta=delta,
        )

    # 2b) Ask next question
    if isinstance(s, TriageStep):
        return LinearTriageResult(
            action="ask",
            say=s.question,
            triage_step_index=i + 1,
            current_question_key=s.key,
            triage_answers_delta=delta,
        )

    # Unknown sentinel (shouldn't happen)
    return LinearTriageResult(
        action="done",
        say=None,
        triage_step_index=i,
        current_question_key=None,
        triage_answers_delta=delta,
    )

