"""
Tests for the LLM-powered triage dialogue manager.

Tests verify:
- PatientState slot management and known_slots() output.
- _apply_extracted_facts correctly maps LLM output to patient state.
- build_command_center_update dedup logic.
- TriageDialogueManager.process_turn() return shape and fallback behavior.
"""

from __future__ import annotations

import time

import pytest

from himpublic.orchestrator.dialogue_manager import (
    BleedingSeverity,
    Consciousness,
    DialogueState,
    PatientState,
    SlotConfidence,
    TriageDialogueManager,
    build_command_center_update,
    _apply_extracted_facts,
)


# ---------------------------------------------------------------------------
# PatientState tests
# ---------------------------------------------------------------------------

class TestPatientState:
    """Test PatientState slot management."""

    def test_initial_state_all_unknown(self):
        ps = PatientState()
        known = ps.known_slots()
        assert known == {}

    def test_set_slot_and_known(self):
        ps = PatientState()
        ps.set_slot("needs_help", True, SlotConfidence.HIGH)
        assert ps.needs_help is True
        assert ps.known_slots()["needs_help"] is True

    def test_high_confidence_not_overwritten_by_low(self):
        """Don't overwrite HIGH-confidence slot with LOW-confidence conflicting value."""
        ps = PatientState()
        ps.set_slot("major_bleeding", True, SlotConfidence.HIGH)
        ps.set_slot("major_bleeding", False, SlotConfidence.LOW)
        assert ps.major_bleeding is True

    def test_enum_slot_serialization(self):
        ps = PatientState()
        ps.set_slot("bleeding_severity", BleedingSeverity.SEVERE, SlotConfidence.HIGH)
        known = ps.known_slots()
        assert known["bleeding_severity"] == "severe"

    def test_to_dict_includes_all_slots(self):
        ps = PatientState()
        ps.set_slot("needs_help", True)
        d = ps.to_dict()
        assert "needs_help" in d
        assert "major_bleeding" in d  # included even if None

    def test_list_slots_empty_not_known(self):
        ps = PatientState()
        assert "pain_locations" not in ps.known_slots()
        assert "hazards_present" not in ps.known_slots()

    def test_list_slots_known_when_populated(self):
        ps = PatientState()
        ps.pain_locations.append("left leg")
        assert "pain_locations" in ps.known_slots()


# ---------------------------------------------------------------------------
# _apply_extracted_facts tests
# ---------------------------------------------------------------------------

class TestApplyExtractedFacts:
    """Test that LLM-extracted facts are correctly applied to PatientState."""

    def test_basic_bool_extraction(self):
        ps = PatientState()
        facts = {"needs_help": True, "major_bleeding": False}
        new = _apply_extracted_facts(ps, facts)
        assert ps.needs_help is True
        assert ps.major_bleeding is False
        assert new["needs_help"] is True
        assert new["major_bleeding"] is False

    def test_null_values_ignored(self):
        ps = PatientState()
        facts = {"needs_help": True, "major_bleeding": None}
        new = _apply_extracted_facts(ps, facts)
        assert "needs_help" in new
        assert "major_bleeding" not in new
        assert ps.major_bleeding is None

    def test_enum_string_mapping(self):
        ps = PatientState()
        facts = {"bleeding_severity": "severe", "conscious": "alert"}
        new = _apply_extracted_facts(ps, facts)
        assert ps.bleeding_severity == BleedingSeverity.SEVERE
        assert ps.conscious == Consciousness.ALERT

    def test_invalid_enum_string_skipped(self):
        ps = PatientState()
        facts = {"bleeding_severity": "extreme"}
        new = _apply_extracted_facts(ps, facts)
        assert ps.bleeding_severity == BleedingSeverity.UNKNOWN
        assert "bleeding_severity" not in new

    def test_pain_locations_merged(self):
        ps = PatientState()
        ps.pain_locations.append("left leg")
        facts = {"pain_locations": ["right arm", "left leg"]}
        new = _apply_extracted_facts(ps, facts)
        assert "left leg" in ps.pain_locations
        assert "right arm" in ps.pain_locations
        assert len(ps.pain_locations) == 2  # no duplicates

    def test_hazards_merged(self):
        ps = PatientState()
        ps.hazards_present.append("fire")
        facts = {"hazards_present": ["smoke", "fire"]}
        new = _apply_extracted_facts(ps, facts)
        assert "fire" in ps.hazards_present
        assert "smoke" in ps.hazards_present
        assert len(ps.hazards_present) == 2

    def test_pain_score_applied(self):
        ps = PatientState()
        facts = {"pain_score": 7}
        new = _apply_extracted_facts(ps, facts)
        assert ps.pain_score == 7
        assert new["pain_score"] == 7


# ---------------------------------------------------------------------------
# Command center dedup tests
# ---------------------------------------------------------------------------

class TestCommandCenterDedup:
    """Test that command center updates are dedup'd."""

    def test_no_update_without_new_facts(self):
        ps = PatientState()
        ds = DialogueState()
        now = time.monotonic()
        payload = build_command_center_update(ps, {}, ds, now)
        assert payload is None  # no new facts, no send

    def test_update_with_new_facts(self):
        ps = PatientState()
        ps.major_bleeding = True
        ds = DialogueState()
        now = time.monotonic()
        payload = build_command_center_update(ps, {"major_bleeding": True}, ds, now)
        assert payload is not None
        assert payload["event"] == "triage_update"

    def test_duplicate_payload_suppressed(self):
        ps = PatientState()
        ps.major_bleeding = True
        ds = DialogueState()
        now = time.monotonic()
        # First send
        p1 = build_command_center_update(ps, {"major_bleeding": True}, ds, now)
        assert p1 is not None
        # Same state, same facts -> should be suppressed
        p2 = build_command_center_update(ps, {"major_bleeding": True}, ds, now + 1)
        assert p2 is None

    def test_new_info_triggers_new_send(self):
        ps = PatientState()
        ps.major_bleeding = True
        ds = DialogueState()
        now = time.monotonic()
        p1 = build_command_center_update(ps, {"major_bleeding": True}, ds, now)
        assert p1 is not None
        # New info added
        ps.bleeding_location = "left leg"
        p2 = build_command_center_update(ps, {"bleeding_location": "left leg"}, ds, now + 1)
        assert p2 is not None


# ---------------------------------------------------------------------------
# TriageDialogueManager process_turn return shape tests
# ---------------------------------------------------------------------------

class TestTriageDialogueManagerReturnShape:
    """Test that process_turn() returns the expected dict shape regardless of LLM availability."""

    def test_return_keys_present(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        r = dm.process_turn(None, None, now)
        assert "question_key" in r
        assert "question_text" in r
        assert "robot_utterance" in r
        assert "new_facts" in r
        assert "command_center_payload" in r
        assert "triage_complete" in r
        assert "triage_answers" in r

    def test_robot_utterance_is_string(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        r = dm.process_turn(None, None, now)
        assert isinstance(r["robot_utterance"], str)
        assert len(r["robot_utterance"]) > 0

    def test_triage_answers_is_dict(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        r = dm.process_turn(None, None, now)
        assert isinstance(r["triage_answers"], dict)

    def test_new_facts_is_dict(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        r = dm.process_turn(None, None, now)
        assert isinstance(r["new_facts"], dict)

    def test_fallback_provides_first_question(self):
        """Without OPENAI_API_KEY, fallback should still provide a question."""
        import os
        old_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            dm = TriageDialogueManager()
            now = time.monotonic()
            r = dm.process_turn(None, None, now)
            assert r["robot_utterance"]  # should not be empty
            assert r["question_key"] is not None  # should have a question
        finally:
            if old_key is not None:
                os.environ["OPENAI_API_KEY"] = old_key

    def test_conversation_history_grows(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        dm.process_turn(None, None, now)
        assert len(dm.dialogue_state.conversation_history) >= 1
        now += 1
        dm.process_turn("yes I need help", "needs_help", now)
        assert len(dm.dialogue_state.conversation_history) >= 2

    def test_get_initial_greeting(self):
        dm = TriageDialogueManager()
        r = dm.get_initial_greeting()
        assert "robot_utterance" in r
        assert isinstance(r["robot_utterance"], str)
