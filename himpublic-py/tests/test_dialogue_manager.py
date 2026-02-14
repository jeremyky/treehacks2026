"""
Regression tests for the slot-based triage dialogue manager.

Tests use a realistic transcript to verify:
- After "in my left leg", next question is about severity/control, NOT location again.
- Only one command-center send per new fact.
- No repeated questions.
- Correct slot extraction.
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
    choose_next_question,
    parse_victim_utterance,
)


# ---------------------------------------------------------------------------
# Transcript for regression test (simulated conversation)
# ---------------------------------------------------------------------------

TRANSCRIPT = [
    # (robot_question_key, victim_response)
    ("needs_help", "yes I need help"),
    ("major_bleeding", "yes there is bleeding"),
    ("bleeding_location", "in my left leg"),
    # BUG in old system: would ask "where is the bleeding?" again here
    # NEW system should ask about severity/control
]


class TestParseVictimUtterance:
    """Test NLU extraction from victim text."""

    def test_needs_help_yes(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("yes I need help", ps, "needs_help")
        assert facts.get("needs_help") is True
        assert conf["needs_help"] == SlotConfidence.HIGH

    def test_needs_help_injury_mention(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("I'm bleeding and hurt", ps, "needs_help")
        assert facts.get("needs_help") is True

    def test_bleeding_yes(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("yes", ps, "major_bleeding")
        assert facts.get("major_bleeding") is True

    def test_bleeding_no(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("no", ps, "major_bleeding")
        assert facts.get("major_bleeding") is False

    def test_bleeding_mentioned_unprompted(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("there's bleeding", ps, "needs_help")
        assert facts.get("major_bleeding") is True

    def test_bleeding_location_left_leg(self):
        ps = PatientState()
        ps.major_bleeding = True
        ps, facts, conf = parse_victim_utterance("in my left leg", ps, "bleeding_location")
        assert facts.get("bleeding_location") == "left leg"
        assert conf.get("bleeding_location") == SlotConfidence.HIGH

    def test_bleeding_without_location(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("there's bleeding", ps, "major_bleeding")
        assert facts.get("major_bleeding") is True
        assert "bleeding_location" not in facts  # location unknown

    def test_breathing_distress(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("yes I can't breathe well", ps, "breathing_distress")
        assert facts.get("breathing_distress") is True

    def test_pain_score_extraction(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("my pain is about 7 out of 10", ps, "pain")
        assert facts.get("pain_score") == 7

    def test_consciousness_inferred_from_speech(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("yes I need help please", ps, "needs_help")
        assert facts.get("conscious") == Consciousness.ALERT

    def test_hazard_detection(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("there's smoke everywhere", ps, None)
        assert "smoke" in facts.get("hazards_present", [])

    def test_partial_update_no_overwrite(self):
        """Don't overwrite HIGH-confidence slot with LOW-confidence conflicting value."""
        ps = PatientState()
        ps.set_slot("major_bleeding", True, SlotConfidence.HIGH)
        ps, facts, conf = parse_victim_utterance("maybe not", ps, "needs_help")
        # major_bleeding should still be True
        assert ps.major_bleeding is True

    def test_trapped_detection(self):
        ps = PatientState()
        ps, facts, conf = parse_victim_utterance("I'm stuck and can't move", ps, "trapped_or_cant_move")
        assert facts.get("trapped_or_cant_move") is True


class TestChooseNextQuestion:
    """Test priority-based question selection."""

    def test_first_question_is_needs_help(self):
        ps = PatientState()
        ds = DialogueState()
        key, text = choose_next_question(ps, ds)
        assert key == "needs_help"

    def test_after_needs_help_asks_bleeding(self):
        ps = PatientState()
        ps.set_slot("needs_help", True, SlotConfidence.HIGH)
        ps.set_slot("conscious", Consciousness.ALERT, SlotConfidence.MEDIUM)
        ds = DialogueState()
        key, text = choose_next_question(ps, ds)
        assert key == "major_bleeding"

    def test_after_bleeding_yes_asks_location(self):
        ps = PatientState()
        ps.set_slot("needs_help", True, SlotConfidence.HIGH)
        ps.set_slot("conscious", Consciousness.ALERT, SlotConfidence.MEDIUM)
        ps.set_slot("major_bleeding", True, SlotConfidence.HIGH)
        ds = DialogueState()
        key, text = choose_next_question(ps, ds)
        assert key == "bleeding_location"

    def test_after_location_known_asks_severity(self):
        """Core regression: after location is known, should ask severity, NOT location again."""
        ps = PatientState()
        ps.set_slot("needs_help", True, SlotConfidence.HIGH)
        ps.set_slot("conscious", Consciousness.ALERT, SlotConfidence.MEDIUM)
        ps.set_slot("major_bleeding", True, SlotConfidence.HIGH)
        ps.set_slot("bleeding_location", "left leg", SlotConfidence.HIGH)
        ds = DialogueState()
        key, text = choose_next_question(ps, ds)
        assert key == "bleeding_severity", f"Expected bleeding_severity but got {key}"
        assert "location" not in (text or "").lower() or "bleeding" in (text or "").lower()

    def test_skips_recently_asked(self):
        ps = PatientState()
        ds = DialogueState()
        now = time.monotonic()
        # Mark needs_help as asked recently
        ds.asked_question_keys["needs_help"] = now
        ds.asked_question_turns["needs_help"] = ds.turn_index
        key, text = choose_next_question(ps, ds, now + 1)
        assert key != "needs_help"

    def test_no_repeat_when_all_known(self):
        """If all high-priority slots are filled, don't repeat them."""
        ps = PatientState()
        ps.set_slot("needs_help", True, SlotConfidence.HIGH)
        ps.set_slot("conscious", Consciousness.ALERT, SlotConfidence.HIGH)
        ps.set_slot("major_bleeding", False, SlotConfidence.HIGH)
        ps.set_slot("breathing_distress", False, SlotConfidence.HIGH)
        ps.set_slot("chest_injury", False, SlotConfidence.HIGH)
        ps.set_slot("shock_signs", False, SlotConfidence.HIGH)
        ps.set_slot("trapped_or_cant_move", False, SlotConfidence.HIGH)
        ps.set_slot("head_injury", False, SlotConfidence.HIGH)
        ds = DialogueState()
        key, text = choose_next_question(ps, ds)
        # Should ask lower-priority questions (hazards, pain, etc.), NOT repeat life threats
        assert key not in ("needs_help", "major_bleeding", "breathing_distress", "conscious")

    def test_bleeding_followup_skipped_when_no_bleeding(self):
        """Bleeding location/severity questions have prerequisite: major_bleeding=True."""
        ps = PatientState()
        ps.set_slot("needs_help", True, SlotConfidence.HIGH)
        ps.set_slot("conscious", Consciousness.ALERT, SlotConfidence.HIGH)
        ps.set_slot("major_bleeding", False, SlotConfidence.HIGH)
        ds = DialogueState()
        key, text = choose_next_question(ps, ds)
        assert key not in ("bleeding_location", "bleeding_severity")


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
        # Same state, same facts → should be suppressed
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


class TestTriageDialogueManagerTranscript:
    """
    End-to-end regression test using the transcript.
    Feeds transcript lines through the dialogue manager and asserts:
    - After "in my left leg" the next question is about severity/control, not location.
    - Only one command-center send per new fact.
    """

    def test_transcript_no_repeat_location_question(self):
        dm = TriageDialogueManager()
        now = time.monotonic()

        # Turn 0: Robot asks first question (needs_help)
        r0 = dm.process_turn(None, None, now)
        assert r0["question_key"] == "needs_help"

        # Turn 1: Victim says "yes I need help"
        now += 1
        r1 = dm.process_turn("yes I need help", "needs_help", now)
        assert r1["new_facts"].get("needs_help") is True
        # Next question should be about major_bleeding (life threat, priority 2)
        assert r1["question_key"] == "major_bleeding"

        # Turn 2: Victim says "yes there is bleeding"
        now += 1
        r2 = dm.process_turn("yes there is bleeding", "major_bleeding", now)
        assert r2["new_facts"].get("major_bleeding") is True
        # Next should be bleeding_location (since we know there IS bleeding)
        assert r2["question_key"] == "bleeding_location"

        # Turn 3: Victim says "in my left leg"
        now += 1
        r3 = dm.process_turn("in my left leg", "bleeding_location", now)
        assert r3["new_facts"].get("bleeding_location") == "left leg"
        # KEY ASSERTION: Next question should be about severity, NOT location again
        assert r3["question_key"] == "bleeding_severity", (
            f"After 'in my left leg', expected bleeding_severity but got {r3['question_key']}"
        )
        # Robot utterance should mention left leg and ask about severity
        assert "left leg" in r3["robot_utterance"].lower()
        assert r3["question_key"] != "bleeding_location"

    def test_transcript_one_cc_send_per_new_fact(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        cc_sends = 0

        # Turn 0: initial
        r0 = dm.process_turn(None, None, now)
        if r0["command_center_payload"] is not None:
            cc_sends += 1

        # Turn 1: "yes I need help"
        now += 1
        r1 = dm.process_turn("yes I need help", "needs_help", now)
        if r1["command_center_payload"] is not None:
            cc_sends += 1
        assert cc_sends <= 1  # at most one send for the first fact

        # Turn 2: "yes there is bleeding"
        now += 1
        r2 = dm.process_turn("yes there is bleeding", "major_bleeding", now)
        if r2["command_center_payload"] is not None:
            cc_sends += 1
        assert cc_sends <= 2  # one per new fact batch

        # Turn 3: "in my left leg"
        now += 1
        r3 = dm.process_turn("in my left leg", "bleeding_location", now)
        if r3["command_center_payload"] is not None:
            cc_sends += 1
        assert cc_sends <= 3  # one per new fact batch

    def test_no_double_ack_messages(self):
        """Robot should not say 'sent to command center' repeatedly for the same info."""
        dm = TriageDialogueManager()
        now = time.monotonic()

        r0 = dm.process_turn(None, None, now)
        now += 1
        r1 = dm.process_turn("yes I need help", "needs_help", now)

        # The utterance should be a single concise turn, not repeated confirmations
        assert r1["robot_utterance"].count("command center") <= 1
        assert r1["robot_utterance"].count("Sent to") <= 1
        assert r1["robot_utterance"].count("Updated") <= 1

    def test_full_triage_progression(self):
        """Walk through a longer conversation and verify no repeated questions."""
        dm = TriageDialogueManager()
        now = time.monotonic()
        asked_keys: list[str] = []

        # Initial greeting
        r = dm.process_turn(None, None, now)
        if r["question_key"]:
            asked_keys.append(r["question_key"])

        exchanges = [
            ("yes I need help", "needs_help"),
            ("yes there is bleeding", "major_bleeding"),
            ("in my left leg", "bleeding_location"),
            ("it's heavy, soaking through", "bleeding_severity"),
            ("yes I can talk fine", "airway_talking"),
            ("no trouble breathing", "breathing_distress"),
            ("no chest injury", "chest_injury"),
            ("I feel a bit dizzy", "shock_signs"),
            ("no I can move", "trapped_or_cant_move"),
            ("no I didn't hit my head", "head_injury"),
        ]

        for victim_text, q_key in exchanges:
            now += 1
            r = dm.process_turn(victim_text, q_key, now)
            next_key = r["question_key"]
            if next_key:
                asked_keys.append(next_key)

        # Verify no question was asked more than once in sequence
        for i in range(1, len(asked_keys)):
            if asked_keys[i] == asked_keys[i - 1]:
                pytest.fail(f"Question '{asked_keys[i]}' asked consecutively at positions {i-1} and {i}")


class TestRobotUtterance:
    """Test that robot utterances are single concise turns."""

    def test_utterance_has_ack_and_question(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        dm.process_turn(None, None, now)  # initial
        now += 1
        r = dm.process_turn("yes I need help", "needs_help", now)
        utterance = r["robot_utterance"]
        # Should contain both an ack and a question
        assert len(utterance) > 10
        # Should not be excessively long (single concise turn)
        assert len(utterance) < 300

    def test_utterance_for_bleeding_location(self):
        dm = TriageDialogueManager()
        now = time.monotonic()
        dm.process_turn(None, None, now)
        now += 1
        dm.process_turn("yes I need help", "needs_help", now)
        now += 1
        dm.process_turn("yes heavy bleeding", "major_bleeding", now)
        now += 1
        r = dm.process_turn("in my left leg", "bleeding_location", now)
        utterance = r["robot_utterance"]
        # Should acknowledge the location and ask about severity
        assert "left leg" in utterance.lower()
        assert "?" in utterance  # should contain a question
