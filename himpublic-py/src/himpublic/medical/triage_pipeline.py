"""
TriagePipeline — coordinator that wires MedicalAssessor + EvidenceCollector
+ QuestionPlanner + ReportBuilder into the orchestrator agent's async loop.

Usage (from OrchestratorAgent):
    pipeline = TriagePipeline(output_dir="reports")
    pipeline.push_frame(frame)              # every perception tick
    findings = pipeline.assess_latest()     # when in INJURY_DETECTION phase
    pipeline.collect_evidence()             # when above threshold
    questions = pipeline.next_questions()   # for ASSIST_COMMUNICATE
    path = pipeline.build_report(...)       # for REPORT_SEND
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from .schemas import Finding, TriageReport
from .medical_assessor import MedicalAssessor
from .evidence_collector import EvidenceCollector, DEFAULT_BUFFER_SIZE, MAX_VIEWS
from .question_planner import QuestionPlanner
from .report_builder import ReportBuilder

logger = logging.getLogger(__name__)

# Minimum confidence to trigger evidence collection / question planning
DEFAULT_FINDING_THRESHOLD = 0.55


class TriagePipeline:
    """
    Aggregates all medical triage subsystems into a single coordinator.

    Thread-safe for single-writer (orchestrator perception loop).
    """

    def __init__(
        self,
        output_dir: str | Path = "reports",
        evidence_dir: str | Path | None = None,
        finding_threshold: float = DEFAULT_FINDING_THRESHOLD,
        injury_prompts: list[str] | None = None,
        use_pose: bool = True,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._evidence_dir = Path(evidence_dir) if evidence_dir else self._output_dir / "evidence"
        self._threshold = finding_threshold

        self._assessor = MedicalAssessor(
            prompts=injury_prompts,
            use_pose=use_pose,
        )
        self._collector = EvidenceCollector(
            output_dir=self._evidence_dir,
            buffer_size=DEFAULT_BUFFER_SIZE,
            max_views=MAX_VIEWS,
        )
        self._planner = QuestionPlanner()
        self._builder = ReportBuilder(output_dir=self._output_dir)

        # Running state
        self._latest_findings: list[Finding] = []
        self._all_findings: list[Finding] = []    # accumulated across frames
        self._evidence_collected: bool = False
        self._report_path: str | None = None
        self._assess_count: int = 0
        # Body region from speech ("Where are you hurt?" -> "my knee"); overrides CV/pose.
        self._spoken_body_region: str | None = None

    # ── Per-frame interface ────────────────────────────────────

    def push_frame(self, frame_bgr: np.ndarray) -> None:
        """Push a frame into the evidence collector's rolling buffer."""
        self._collector.push_frame(frame_bgr)

    def assess(self, frame_bgr: np.ndarray) -> list[Finding]:
        """
        Run the medical assessor on a single frame.

        Returns findings and updates internal state.
        """
        self._assess_count += 1
        findings = self._assessor.assess(frame_bgr)
        self._latest_findings = findings

        # Accumulate findings above threshold
        for f in findings:
            if f.confidence >= self._threshold:
                # Avoid duplicates from same region (keep higher confidence)
                existing = next(
                    (e for e in self._all_findings if e.body_region == f.body_region and e.finding_type == f.finding_type),
                    None,
                )
                if existing is None:
                    self._all_findings.append(f)
                elif f.confidence > existing.confidence:
                    self._all_findings.remove(existing)
                    self._all_findings.append(f)

        return findings

    @property
    def latest_findings(self) -> list[Finding]:
        return list(self._latest_findings)

    @property
    def accumulated_findings(self) -> list[Finding]:
        return list(self._all_findings)

    @property
    def has_significant_findings(self) -> bool:
        return any(f.confidence >= self._threshold for f in self._all_findings)

    # ── Evidence collection ───────────────────────────────────

    def collect_evidence(self, victim_id: str | None = None) -> Path | None:
        """Collect evidence for all accumulated findings above threshold."""
        significant = [f for f in self._all_findings if f.confidence >= self._threshold]
        if not significant:
            logger.info("TriagePipeline: no significant findings to collect evidence for.")
            return None
        result = self._collector.collect(significant, victim_id=victim_id)
        if result:
            self._evidence_collected = True
        return result

    # ── Spoken body region (from "Where are you hurt?") ─────────

    def set_spoken_body_region(self, region: str | None) -> None:
        """
        Set body part from victim's words (e.g. "my knee", "left arm").
        Overrides CV/pose for report and questions. Call after they answer "Where are you hurt?"
        """
        self._spoken_body_region = (region or "").strip() or None
        if self._spoken_body_region:
            for f in self._all_findings:
                f.body_region = self._spoken_body_region
            for f in self._latest_findings:
                f.body_region = self._spoken_body_region
            logger.info("TriagePipeline: body_region set from speech: %s", self._spoken_body_region)

    @property
    def spoken_body_region(self) -> str | None:
        return self._spoken_body_region

    # ── Question planning ─────────────────────────────────────

    def next_questions(self, max_questions: int = 4) -> list[dict[str, Any]]:
        """Get next triage questions based on accumulated findings. Uses spoken body region if set."""
        significant = [f for f in self._all_findings if f.confidence >= self._threshold]
        questions = self._planner.next_questions(
            significant, max_questions=max_questions,
            spoken_body_region=self._spoken_body_region,
        )
        return [
            {"id": q.id, "text": q.text, "finding_ref": q.finding_ref, "category": q.category}
            for q in questions
        ]

    def mark_question_answered(self, question_id: str, answer: str) -> None:
        self._planner.mark_answered(question_id, answer)

    def get_victim_answers(self) -> dict[str, str]:
        return self._planner.get_answers()

    # ── Report building ───────────────────────────────────────

    def build_report(
        self,
        scene_summary: str = "",
        victim_answers: dict[str, str] | None = None,
        notes: list[str] | None = None,
        conversation_transcript: list[str] | None = None,
        scene_images: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str | None:
        """Build a complete triage report (Markdown) and return the file path."""
        # Merge planner answers with any additional victim answers
        all_answers = dict(self._planner.get_answers())
        if victim_answers:
            all_answers.update(victim_answers)

        report = TriageReport(
            scene_summary=scene_summary or "Automated triage assessment by rescue robot.",
            victim_answers=all_answers,
            findings=self._all_findings,
            notes=notes or [],
            conversation_transcript=list(conversation_transcript or []),
            scene_images=list(scene_images or []),
        )

        path = self._builder.build_report(report, meta=meta, scene_summary=scene_summary)
        self._report_path = path
        return path

    def render_report_string(
        self,
        scene_summary: str = "",
        victim_answers: dict[str, str] | None = None,
        conversation_transcript: list[str] | None = None,
        scene_images: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Render report as a Markdown string (no file I/O)."""
        all_answers = dict(self._planner.get_answers())
        if victim_answers:
            all_answers.update(victim_answers)

        report = TriageReport(
            scene_summary=scene_summary or "Automated triage assessment by rescue robot.",
            victim_answers=all_answers,
            findings=self._all_findings,
            conversation_transcript=list(conversation_transcript or []),
            scene_images=list(scene_images or []),
        )
        return self._builder.render_string(report, meta=meta)

    @property
    def report_path(self) -> str | None:
        return self._report_path

    # ── Conversion helpers (bridge to existing report schema) ─

    def findings_to_suspected_injuries(self) -> list[dict[str, Any]]:
        """Convert findings to dicts compatible with medical.report_schema.SuspectedInjury."""
        return [
            {
                "injury_type": f.finding_type.replace("suspected_", ""),
                "body_location": f.body_region,
                "severity_estimate": f.severity,
                "confidence": f.confidence,
                "rationale": f.label,
                "immediate_actions_recommended": [
                    _action_for_finding(f),
                ],
                "evidence_ids": [],
            }
            for f in self._all_findings
            if f.confidence >= self._threshold
        ]

    def findings_summary(self) -> dict[str, Any]:
        """Compact summary dict for command center telemetry."""
        return {
            "total_assessed_frames": self._assess_count,
            "total_accumulated_findings": len(self._all_findings),
            "significant_findings": len([f for f in self._all_findings if f.confidence >= self._threshold]),
            "evidence_collected": self._evidence_collected,
            "report_path": self._report_path,
            "findings": [
                {
                    "type": f.finding_type,
                    "label": f.label,
                    "confidence": round(f.confidence, 3),
                    "severity": f.severity,
                    "region": f.body_region,
                }
                for f in self._all_findings
            ],
        }

    # ── Reset ─────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all state (new victim / new session)."""
        self._latest_findings.clear()
        self._all_findings.clear()
        self._evidence_collected = False
        self._report_path = None
        self._assess_count = 0
        self._spoken_body_region = None
        self._planner.reset()


def _action_for_finding(f: Finding) -> str:
    """One-line recommended action for a finding."""
    if f.severity == "high" and "bleeding" in f.finding_type:
        return "Request immediate responder; apply direct pressure"
    if f.severity == "high":
        return "Urgent attention recommended"
    if f.severity == "medium":
        return "Monitor closely; reassess in 5 minutes"
    return "Continue observation"
