"""
Tests for the strict sequential rescue pipeline.
Verifies ordering enforcement, preconditions, retry logic, and artifact generation.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from himpublic.pipeline.engine import (
    MissionContext,
    MissionLogger,
    PhaseDefinition,
    PhaseResult,
    PhaseStatus,
    PipelineRunner,
    RetryPolicy,
)
from himpublic.pipeline.phases import PIPELINE_PHASES, PipelinePhase


class TestPipelineOrdering:
    """Verify strict sequential ordering."""

    def test_all_7_phases_defined(self):
        assert len(PIPELINE_PHASES) == 7

    def test_phase_order_is_canonical(self):
        expected = [
            PipelinePhase.DEPLOY,
            PipelinePhase.SEARCH_HAIL,
            PipelinePhase.APPROACH_CONFIRM,
            PipelinePhase.DEBRIS_CLEAR,
            PipelinePhase.TRIAGE_DIALOG_SCAN,
            PipelinePhase.REPORT_SEND,
            PipelinePhase.MONITOR_WAIT,
        ]
        actual = [p.name for p in PIPELINE_PHASES]
        assert actual == expected

    def test_demo_run_completes_all_phases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(
                phases=PIPELINE_PHASES,
                mode="demo",
                run_id="test_ordering",
                output_dir=tmpdir,
            )
            ctx = runner.run()
            assert ctx.completed_phases == [
                "DEPLOY", "SEARCH_HAIL", "APPROACH_CONFIRM", "DEBRIS_CLEAR",
                "TRIAGE_DIALOG_SCAN", "REPORT_SEND", "MONITOR_WAIT",
            ]
            assert ctx.mission_complete is True

    def test_phases_execute_in_order(self):
        """Verify phase results are stored in order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(
                phases=PIPELINE_PHASES,
                mode="demo",
                run_id="test_order_check",
                output_dir=tmpdir,
            )
            ctx = runner.run()
            result_keys = list(ctx.phase_results.keys())
            assert result_keys == [p.name for p in PIPELINE_PHASES]


class TestForcePhase:
    """Test --force_phase skipping."""

    def test_force_phase_skips_earlier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(
                phases=PIPELINE_PHASES,
                mode="demo",
                run_id="test_force",
                output_dir=tmpdir,
                force_phase="TRIAGE_DIALOG_SCAN",
            )
            ctx = runner.run()
            # First 4 phases should be SKIPPED
            for phase_name in ["DEPLOY", "SEARCH_HAIL", "APPROACH_CONFIRM", "DEBRIS_CLEAR"]:
                assert ctx.phase_results[phase_name]["status"] == "skipped"
            # TRIAGE and later should be executed (might fail preconditions in force mode, 
            # but they should be attempted)
            assert "TRIAGE_DIALOG_SCAN" in ctx.completed_phases


class TestRetryPolicy:
    """Test retry and failure logic."""

    def test_retry_on_fail(self):
        attempt_count = 0

        def failing_handler(ctx: MissionContext) -> PhaseResult:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                return PhaseResult(status=PhaseStatus.FAIL, reason="simulated failure")
            return PhaseResult(status=PhaseStatus.SUCCESS, reason="finally worked")

        phases = [
            PhaseDefinition(
                name="TEST_RETRY",
                label="Test retry",
                handler=failing_handler,
                retry_policy=RetryPolicy(max_attempts=3, cooldown_s=0.01),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(phases=phases, mode="demo", run_id="test_retry", output_dir=tmpdir)
            ctx = runner.run()
            assert attempt_count == 3
            assert ctx.phase_results["TEST_RETRY"]["status"] == "success"

    def test_abort_on_exhausted_retries(self):
        def always_fails(ctx: MissionContext) -> PhaseResult:
            return PhaseResult(status=PhaseStatus.FAIL, reason="always fails")

        phases = [
            PhaseDefinition(
                name="TEST_ABORT",
                label="Test abort",
                handler=always_fails,
                retry_policy=RetryPolicy(max_attempts=2, cooldown_s=0.01,
                                         allow_degraded=False, fallback_status=PhaseStatus.ABORT),
            ),
            PhaseDefinition(
                name="SHOULD_NOT_RUN",
                label="Should not run",
                handler=lambda ctx: PhaseResult(status=PhaseStatus.SUCCESS),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(phases=phases, mode="demo", run_id="test_abort", output_dir=tmpdir)
            ctx = runner.run()
            assert ctx.phase_results["TEST_ABORT"]["status"] == "abort"
            assert "SHOULD_NOT_RUN" not in ctx.phase_results

    def test_degraded_on_exhausted_retries(self):
        def always_fails(ctx: MissionContext) -> PhaseResult:
            return PhaseResult(status=PhaseStatus.FAIL, reason="always fails")

        phases = [
            PhaseDefinition(
                name="TEST_DEGRADED",
                label="Test degraded",
                handler=always_fails,
                retry_policy=RetryPolicy(max_attempts=2, cooldown_s=0.01, allow_degraded=True),
            ),
            PhaseDefinition(
                name="NEXT_PHASE",
                label="Next",
                handler=lambda ctx: PhaseResult(status=PhaseStatus.SUCCESS),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(phases=phases, mode="demo", run_id="test_degraded", output_dir=tmpdir)
            ctx = runner.run()
            # Should proceed despite failure
            assert "NEXT_PHASE" in ctx.phase_results
            assert ctx.phase_results["NEXT_PHASE"]["status"] == "success"


class TestPreconditions:
    """Test precondition enforcement."""

    def test_precondition_failure_aborts(self):
        def bad_precondition(ctx: MissionContext) -> tuple[bool, str]:
            return False, "test precondition failure"

        phases = [
            PhaseDefinition(
                name="TEST_PRECON",
                label="Test precondition",
                handler=lambda ctx: PhaseResult(status=PhaseStatus.SUCCESS),
                retry_policy=RetryPolicy(max_attempts=1, allow_degraded=False),
                preconditions=[bad_precondition],
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(phases=phases, mode="demo", run_id="test_precon", output_dir=tmpdir)
            ctx = runner.run()
            assert ctx.phase_results["TEST_PRECON"]["status"] == "abort"


class TestArtifacts:
    """Test that mission artifacts are saved correctly."""

    def test_artifacts_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(
                phases=PIPELINE_PHASES,
                mode="demo",
                run_id="test_artifacts",
                output_dir=tmpdir,
            )
            ctx = runner.run()
            mission_dir = Path(tmpdir) / "test_artifacts"
            assert (mission_dir / "log.jsonl").exists()
            assert (mission_dir / "context_snapshot.json").exists()
            assert (mission_dir / "report.json").exists()
            assert (mission_dir / "report.md").exists()
            assert (mission_dir / "images").is_dir()
            assert (mission_dir / "audio").is_dir()

    def test_log_jsonl_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(
                phases=PIPELINE_PHASES,
                mode="demo",
                run_id="test_log",
                output_dir=tmpdir,
            )
            ctx = runner.run()
            log_path = Path(tmpdir) / "test_log" / "log.jsonl"
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) >= 7  # at least one entry per phase
            for line in lines:
                entry = json.loads(line)
                assert "ts" in entry
                assert "msg" in entry

    def test_context_snapshot_loadable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(
                phases=PIPELINE_PHASES,
                mode="demo",
                run_id="test_snap",
                output_dir=tmpdir,
            )
            ctx = runner.run()
            snap_path = Path(tmpdir) / "test_snap" / "context_snapshot.json"
            data = json.loads(snap_path.read_text())
            restored = MissionContext.from_dict(data)
            assert restored.run_id == "test_snap"
            assert restored.mission_complete is True
            assert len(restored.completed_phases) == 7


class TestExplain:
    """Test --explain output."""

    def test_explain_output(self):
        runner = PipelineRunner(phases=PIPELINE_PHASES, mode="demo")
        text = runner.explain()
        assert "WHAT MECHANISM ENFORCES THE PHASE ORDER" in text
        assert "PRECONDITIONS" in text
        assert "MissionContext" in text
        assert "FAILURES" in text
        assert "RESUME" in text
        assert "DEPLOY" in text
        assert "MONITOR_WAIT" in text
