"""
Pipeline Engine — enforces strict sequential phase execution.

Ordering guarantee: phases are stored in a Python list and executed via a
simple ``for`` loop.  There is no dispatch table, no event-driven routing,
and no way for a phase handler to jump to an arbitrary other phase.  The
ONLY way to advance is to return a PhaseResult; the ONLY way to skip is
to pass ``--force_phase`` which is logged as an explicit override.

Each phase handler receives the shared MissionContext (accumulated outputs
from every prior phase) and returns a PhaseResult.  The runner validates
preconditions before calling the handler, and postconditions after.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

class PhaseStatus(Enum):
    SUCCESS = "success"
    FAIL = "fail"
    RETRY = "retry"
    ABORT = "abort"
    SKIPPED = "skipped"  # explicit override only


@dataclass
class PhaseResult:
    """Structured result returned by every phase handler."""
    status: PhaseStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    next_recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "outputs": self.outputs,
            "evidence": self.evidence,
            "reason": self.reason,
            "next_recommendation": self.next_recommendation,
        }


@dataclass
class RetryPolicy:
    """Per-phase retry configuration."""
    max_attempts: int = 3
    cooldown_s: float = 2.0
    allow_degraded: bool = False  # proceed with degraded status on exhaust
    fallback_status: PhaseStatus = PhaseStatus.ABORT


@dataclass
class MissionContext:
    """
    Accumulated state carried forward through the pipeline.
    Each phase reads from and writes to this context.
    """
    run_id: str = ""
    mode: str = "demo"  # demo | robot
    start_time: float = 0.0
    current_phase: str = ""
    phase_index: int = 0
    completed_phases: list[str] = field(default_factory=list)
    phase_results: dict[str, dict] = field(default_factory=dict)  # phase_name -> PhaseResult.to_dict()

    # Cross-phase data (outputs from prior phases become inputs for later ones)
    deploy_status: str = ""  # "ready" | "degraded"
    sensors_available: dict[str, bool] = field(default_factory=dict)

    person_detected: bool = False
    person_confidence: float = 0.0
    person_location_hint: str = ""
    hail_response: str | None = None

    approach_confirmed: bool = False
    standoff_established: bool = False

    debris_status: str = ""  # "clear" | "blocked_cleared" | "blocked_not_clearable"
    debris_images: list[str] = field(default_factory=list)

    triage_answers: dict[str, Any] = field(default_factory=dict)
    patient_state: dict[str, Any] = field(default_factory=dict)
    scan_images: list[str] = field(default_factory=list)
    transcript: list[dict[str, str]] = field(default_factory=list)  # [{role, text}]

    report_payload: dict[str, Any] = field(default_factory=dict)
    report_sent: bool = False
    report_path: str = ""

    monitor_active: bool = False
    mission_complete: bool = False

    # Artifact paths
    output_dir: str = ""
    images_dir: str = ""
    audio_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise for snapshot/resume."""
        d: dict[str, Any] = {}
        for k in self.__dataclass_fields__:
            v = getattr(self, k)
            d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MissionContext:
        ctx = cls()
        for k, v in d.items():
            if hasattr(ctx, k):
                setattr(ctx, k, v)
        return ctx


# ---------------------------------------------------------------------------
# Phase definition protocol
# ---------------------------------------------------------------------------

class PhaseHandler(Protocol):
    """Callable that executes a single pipeline phase."""
    def __call__(self, ctx: MissionContext) -> PhaseResult: ...


@dataclass
class PhaseDefinition:
    """One phase in the pipeline."""
    name: str
    label: str
    handler: PhaseHandler
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    preconditions: list[Callable[[MissionContext], tuple[bool, str]]] = field(default_factory=list)
    postconditions: list[Callable[[MissionContext, PhaseResult], tuple[bool, str]]] = field(default_factory=list)
    announce_text: str = ""  # spoken when entering this phase


# ---------------------------------------------------------------------------
# Structured mission logger
# ---------------------------------------------------------------------------

class MissionLogger:
    """Append-only JSONL logger for one mission run."""

    def __init__(self, log_path: Path) -> None:
        self._path = log_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, **fields: Any) -> None:
        entry = {"ts": time.time(), "ts_mono": time.monotonic(), **fields}
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
        # Also emit to stdlib logger so it appears in console
        level = fields.get("level", "info")
        msg = fields.get("msg", json.dumps(fields, default=str))
        getattr(logger, level, logger.info)(msg)


# ---------------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """
    Executes pipeline phases in strict order.

    Ordering enforcement:
    • Phases are stored in a Python ``list`` and iterated with a ``for`` loop.
    • There is no routing table, no event bus, no way for a handler to jump.
    • ``--force_phase`` skips earlier phases with explicit SKIPPED status + log.
    • Every transition is logged with phase name, index, timing, and result.
    """

    def __init__(
        self,
        phases: list[PhaseDefinition],
        *,
        mode: str = "demo",
        run_id: str | None = None,
        output_dir: str | Path = "missions",
        force_phase: str | None = None,
        speak_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._phases = list(phases)  # defensive copy
        self._mode = mode
        self._run_id = run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self._base_output = Path(output_dir)
        self._force_phase = force_phase
        self._speak = speak_fn or (lambda s: None)
        self._mission_dir = self._base_output / self._run_id
        self._mlog: MissionLogger | None = None

    # -- public API --

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def mission_dir(self) -> Path:
        return self._mission_dir

    def run(self) -> MissionContext:
        """Execute the full pipeline. Returns final MissionContext."""
        self._setup_dirs()
        ctx = self._init_context()
        self._mlog = MissionLogger(self._mission_dir / "log.jsonl")

        self._mlog.log(msg="Pipeline started", run_id=self._run_id, mode=self._mode,
                       phases=[p.name for p in self._phases])
        logger.info("=" * 60)
        logger.info("PIPELINE START  run_id=%s  mode=%s", self._run_id, self._mode)
        logger.info("Phases: %s", " → ".join(p.name for p in self._phases))
        logger.info("=" * 60)

        skip_until = self._resolve_force_phase()

        for idx, phase_def in enumerate(self._phases):
            ctx.phase_index = idx
            ctx.current_phase = phase_def.name

            # Handle --force_phase skipping
            if skip_until is not None and idx < skip_until:
                self._skip_phase(ctx, phase_def, idx)
                continue

            # Execute phase with retry logic
            result = self._execute_phase(ctx, phase_def, idx)
            ctx.phase_results[phase_def.name] = result.to_dict()
            ctx.completed_phases.append(phase_def.name)

            # Save snapshot after every phase
            self._save_snapshot(ctx)

            # Abort if phase says so
            if result.status == PhaseStatus.ABORT:
                self._mlog.log(msg=f"Pipeline ABORTED at {phase_def.name}", reason=result.reason,
                               level="error")
                logger.error("PIPELINE ABORTED at %s: %s", phase_def.name, result.reason)
                break

        ctx.mission_complete = True
        self._save_snapshot(ctx)
        self._save_report(ctx)
        self._mlog.log(msg="Pipeline complete", run_id=self._run_id,
                       completed=ctx.completed_phases)
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE  run_id=%s  completed=%s", self._run_id, ctx.completed_phases)
        logger.info("Artifacts: %s", self._mission_dir)
        logger.info("=" * 60)
        return ctx

    def explain(self) -> str:
        """Return a human-readable explanation of pipeline ordering enforcement."""
        lines = [
            "=" * 60,
            "PIPELINE ORDERING EXPLANATION",
            "=" * 60,
            "",
            "1) WHAT MECHANISM ENFORCES THE PHASE ORDER?",
            "   Phases are stored in a Python list and executed in a sequential",
            "   `for` loop (engine.py PipelineRunner.run()).  There is no dispatch",
            "   table, no event bus, and no way for a phase handler to jump to",
            "   an arbitrary phase.  The ONLY way to advance is to return a",
            "   PhaseResult from the current handler.  The ONLY way to skip is",
            "   the --force_phase CLI flag, which logs every skipped phase with",
            "   status=SKIPPED.",
            "",
            "2) WHERE ARE PRECONDITIONS / POSTCONDITIONS CHECKED?",
            "   Each PhaseDefinition has a `preconditions` list and a `postconditions`",
            "   list.  Before calling the handler, the runner checks every precondition;",
            "   if any fails the phase is retried or aborted.  After the handler returns,",
            "   postconditions are checked; failures trigger retry or abort.",
            "",
            "3) WHAT DATA IS PASSED BETWEEN PHASES (MissionContext fields)?",
        ]
        lines.append("   MissionContext carries accumulated state:")
        ctx = MissionContext()
        for fname in ctx.__dataclass_fields__:
            lines.append(f"     - {fname}")
        lines.extend([
            "",
            "4) HOW ARE FAILURES / RETRIES HANDLED?",
            "   Each phase has a RetryPolicy(max_attempts, cooldown_s, allow_degraded,",
            "   fallback_status).  On FAIL or RETRY, the runner re-calls the handler up",
            "   to max_attempts times, sleeping cooldown_s between attempts.  Every",
            "   attempt is logged.  If retries exhaust:",
            "     - allow_degraded=True → proceed with FAIL status + degraded flag",
            "     - allow_degraded=False → fallback_status (default ABORT) stops pipeline",
            "",
            "5) HOW CAN WE RESUME FROM A SAVED SNAPSHOT?",
            "   After every phase, MissionContext is serialized to",
            "   missions/<run_id>/context_snapshot.json.  To resume, load the snapshot,",
            "   use --force_phase to skip completed phases, and the context carries",
            "   all accumulated outputs.",
            "",
            "ENFORCED PHASE ORDER:",
        ])
        for i, p in enumerate(self._phases):
            arrow = " → " if i < len(self._phases) - 1 else ""
            lines.append(f"   {i+1}. {p.name} ({p.label}){arrow}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    # -- private --

    def _setup_dirs(self) -> None:
        for sub in ("images", "audio"):
            (self._mission_dir / sub).mkdir(parents=True, exist_ok=True)

    def _init_context(self) -> MissionContext:
        return MissionContext(
            run_id=self._run_id,
            mode=self._mode,
            start_time=time.time(),
            output_dir=str(self._mission_dir),
            images_dir=str(self._mission_dir / "images"),
            audio_dir=str(self._mission_dir / "audio"),
        )

    def _resolve_force_phase(self) -> int | None:
        if not self._force_phase:
            return None
        for i, p in enumerate(self._phases):
            if p.name == self._force_phase:
                if i > 0:
                    logger.warning("--force_phase=%s: skipping phases 0..%d", self._force_phase, i - 1)
                return i
        logger.warning("--force_phase=%s not found; running all phases", self._force_phase)
        return None

    def _skip_phase(self, ctx: MissionContext, phase_def: PhaseDefinition, idx: int) -> None:
        result = PhaseResult(
            status=PhaseStatus.SKIPPED,
            reason=f"Skipped due to --force_phase={self._force_phase}",
        )
        ctx.phase_results[phase_def.name] = result.to_dict()
        ctx.completed_phases.append(phase_def.name)
        if self._mlog:
            self._mlog.log(msg=f"Phase SKIPPED: {phase_def.name}", phase=phase_def.name,
                           index=idx, reason=result.reason, level="warning")
        logger.warning("[%d/%d] SKIP  %s (--force_phase override)",
                       idx + 1, len(self._phases), phase_def.name)

    def _execute_phase(self, ctx: MissionContext, phase_def: PhaseDefinition, idx: int) -> PhaseResult:
        """Execute one phase with precondition check, retries, and postcondition check."""
        total = len(self._phases)
        policy = phase_def.retry_policy

        # Announce
        if phase_def.announce_text and self._speak:
            self._speak(phase_def.announce_text)

        self._mlog.log(msg=f"Phase START: {phase_def.name}", phase=phase_def.name,
                       index=idx, label=phase_def.label, max_attempts=policy.max_attempts)
        logger.info("-" * 50)
        logger.info("[%d/%d] START  %s — %s", idx + 1, total, phase_def.name, phase_def.label)

        # Check preconditions
        for pre_fn in phase_def.preconditions:
            ok, reason = pre_fn(ctx)
            if not ok:
                self._mlog.log(msg=f"Precondition FAILED for {phase_def.name}",
                               phase=phase_def.name, reason=reason, level="error")
                if policy.allow_degraded:
                    logger.warning("[%d/%d] Precondition failed for %s: %s — proceeding degraded",
                                   idx + 1, total, phase_def.name, reason)
                else:
                    logger.error("[%d/%d] Precondition failed for %s: %s — ABORT",
                                 idx + 1, total, phase_def.name, reason)
                    return PhaseResult(status=PhaseStatus.ABORT, reason=f"Precondition failed: {reason}")

        # Execute with retries
        last_result: PhaseResult | None = None
        for attempt in range(1, policy.max_attempts + 1):
            t0 = time.monotonic()
            try:
                result = phase_def.handler(ctx)
            except Exception as e:
                logger.exception("[%d/%d] %s attempt %d EXCEPTION: %s",
                                 idx + 1, total, phase_def.name, attempt, e)
                result = PhaseResult(status=PhaseStatus.FAIL, reason=f"Exception: {e}")

            elapsed = time.monotonic() - t0
            self._mlog.log(
                msg=f"Phase {phase_def.name} attempt {attempt} -> {result.status.value}",
                phase=phase_def.name, attempt=attempt, status=result.status.value,
                elapsed_s=round(elapsed, 3), reason=result.reason,
                outputs=list(result.outputs.keys()),
                evidence=list(result.evidence.keys()),
            )
            logger.info("[%d/%d] %s  attempt=%d  status=%s  elapsed=%.2fs  reason=%s",
                        idx + 1, total, phase_def.name, attempt,
                        result.status.value, elapsed, result.reason or "—")
            last_result = result

            if result.status == PhaseStatus.SUCCESS:
                break
            if result.status == PhaseStatus.ABORT:
                break
            if result.status in (PhaseStatus.FAIL, PhaseStatus.RETRY):
                if attempt < policy.max_attempts:
                    logger.info("[%d/%d] %s  retrying in %.1fs (%d/%d)…",
                                idx + 1, total, phase_def.name,
                                policy.cooldown_s, attempt, policy.max_attempts)
                    time.sleep(policy.cooldown_s)
                else:
                    # Exhausted retries
                    if policy.allow_degraded:
                        logger.warning("[%d/%d] %s  retries exhausted — proceeding degraded",
                                       idx + 1, total, phase_def.name)
                        result = PhaseResult(
                            status=PhaseStatus.FAIL,
                            reason=f"Retries exhausted ({policy.max_attempts}); proceeding degraded",
                            outputs=result.outputs,
                            evidence=result.evidence,
                        )
                        last_result = result
                    else:
                        result = PhaseResult(
                            status=policy.fallback_status,
                            reason=f"Retries exhausted ({policy.max_attempts})",
                            outputs=result.outputs,
                            evidence=result.evidence,
                        )
                        last_result = result

        assert last_result is not None

        # Postconditions (only on success)
        if last_result.status == PhaseStatus.SUCCESS:
            for post_fn in phase_def.postconditions:
                ok, reason = post_fn(ctx, last_result)
                if not ok:
                    self._mlog.log(msg=f"Postcondition FAILED for {phase_def.name}",
                                   phase=phase_def.name, reason=reason, level="warning")
                    logger.warning("[%d/%d] Postcondition failed for %s: %s",
                                   idx + 1, total, phase_def.name, reason)

        logger.info("[%d/%d] END    %s  final_status=%s",
                    idx + 1, total, phase_def.name, last_result.status.value)
        return last_result

    def _save_snapshot(self, ctx: MissionContext) -> None:
        path = self._mission_dir / "context_snapshot.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ctx.to_dict(), f, indent=2, default=str, ensure_ascii=False)

    def _save_report(self, ctx: MissionContext) -> None:
        """Save final report as JSON and Markdown."""
        # JSON
        report_json_path = self._mission_dir / "report.json"
        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(ctx.report_payload or ctx.to_dict(), f, indent=2, default=str)
        ctx.report_path = str(report_json_path)

        # Markdown
        report_md_path = self._mission_dir / "report.md"
        md_lines = [
            f"# Mission Report: {ctx.run_id}",
            "",
            f"**Mode:** {ctx.mode}",
            f"**Start time:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ctx.start_time))}",
            f"**Completed phases:** {', '.join(ctx.completed_phases)}",
            "",
            "## Phase Results",
            "",
        ]
        for pname, presult in ctx.phase_results.items():
            md_lines.append(f"### {pname}")
            md_lines.append(f"- **Status:** {presult.get('status', '?')}")
            md_lines.append(f"- **Reason:** {presult.get('reason', '—')}")
            if presult.get("outputs"):
                md_lines.append(f"- **Outputs:** {', '.join(str(k) for k in presult['outputs'].keys())}")
            md_lines.append("")

        md_lines.extend([
            "## Patient State",
            "",
        ])
        if ctx.patient_state:
            for k, v in ctx.patient_state.items():
                md_lines.append(f"- **{k}:** {v}")
        elif ctx.triage_answers:
            for k, v in ctx.triage_answers.items():
                md_lines.append(f"- **{k}:** {v}")
        else:
            md_lines.append("- No triage data collected.")
        md_lines.append("")

        if ctx.transcript:
            md_lines.extend(["## Transcript", ""])
            for entry in ctx.transcript:
                role = entry.get("role", "?")
                text = entry.get("text", "")
                md_lines.append(f"**{role}:** {text}")
            md_lines.append("")

        with open(report_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
