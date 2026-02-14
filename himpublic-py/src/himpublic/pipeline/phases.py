"""
Phase handlers for the strict rescue pipeline.

Each handler receives MissionContext, performs its work, mutates the context
with its outputs, and returns a PhaseResult.

In ``demo`` mode the handlers use placeholders / simulated data so the
pipeline can be run end-to-end without hardware.  In ``robot`` mode the
handlers call into real robot I/O, perception, and audio subsystems (stubs
for now — a teammate wires them up later).

Pipeline order (enforced by engine.py):
  DEPLOY → SEARCH_HAIL → APPROACH_CONFIRM → DEBRIS_CLEAR →
  TRIAGE_DIALOG_SCAN → REPORT_SEND → MONITOR_WAIT
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import (
    MissionContext,
    PhaseDefinition,
    PhaseResult,
    PhaseStatus,
    RetryPolicy,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _demo_sleep(seconds: float) -> None:
    """Short sleep to simulate work in demo mode."""
    time.sleep(min(seconds, 0.3))


def _write_evidence(ctx: MissionContext, name: str, data: str) -> str:
    """Write a text evidence file and return its path."""
    path = Path(ctx.output_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return str(path)


# ======================================================================
# Phase 1: DEPLOY
# ======================================================================

def _deploy_handler(ctx: MissionContext) -> PhaseResult:
    """
    Self-check: verify sensors, comms, battery.
    In demo mode: always succeeds with simulated sensor list.
    In robot mode: would probe actual hardware.
    """
    logger.info("  Checking sensors and systems…")
    _demo_sleep(0.2)

    sensors = {
        "camera": True,
        "microphone": True,
        "speaker": True,
        "motors": ctx.mode == "robot",
        "depth_sensor": False,  # often unavailable
        "comms": True,
    }

    all_critical_ok = sensors["camera"] and sensors["microphone"] and sensors["speaker"]
    status_label = "ready" if all_critical_ok else "degraded"

    ctx.deploy_status = status_label
    ctx.sensors_available = sensors

    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={"deploy_status": status_label, "sensors": sensors},
        evidence={"sensor_check": sensors},
        reason=f"System {status_label} — critical sensors {'all OK' if all_critical_ok else 'PARTIAL'}",
        next_recommendation="Proceed to search and hail.",
    )


def _pre_deploy(_ctx: MissionContext) -> tuple[bool, str]:
    return True, ""  # no preconditions for first phase


def _post_deploy(ctx: MissionContext, result: PhaseResult) -> tuple[bool, str]:
    if not ctx.deploy_status:
        return False, "deploy_status not set"
    return True, ""


# ======================================================================
# Phase 2: SEARCH_HAIL
# ======================================================================

def _search_hail_handler(ctx: MissionContext) -> PhaseResult:
    """
    Search for a person: rotate/scan, hail with voice, listen for response.
    Demo: simulates finding a person after a short delay.
    """
    logger.info("  Searching for victims — rotating and scanning…")
    _demo_sleep(0.3)

    # Simulate detection
    if ctx.mode == "demo":
        ctx.person_detected = True
        ctx.person_confidence = 0.85
        ctx.person_location_hint = "corridor, approx 10m ahead on the left"
        ctx.hail_response = "Help! I'm over here!"
        ctx.transcript.append({"role": "robot", "text": "If anyone can hear me, call out or make a noise!"})
        ctx.transcript.append({"role": "victim", "text": ctx.hail_response})
    else:
        # Robot mode: would use person_detector + audio_io
        ctx.person_detected = False
        ctx.person_confidence = 0.0

    if not ctx.person_detected:
        return PhaseResult(
            status=PhaseStatus.RETRY,
            reason="No person detected — will retry scan",
            outputs={"person_detected": False},
        )

    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={
            "person_detected": True,
            "person_confidence": ctx.person_confidence,
            "location_hint": ctx.person_location_hint,
            "hail_response": ctx.hail_response,
        },
        evidence={"hail_transcript": ctx.hail_response},
        reason=f"Person detected (conf={ctx.person_confidence:.2f})",
        next_recommendation="Approach and confirm identity.",
    )


def _pre_search_hail(ctx: MissionContext) -> tuple[bool, str]:
    if ctx.deploy_status not in ("ready", "degraded"):
        return False, f"Deploy not complete (status={ctx.deploy_status!r})"
    return True, ""


def _post_search_hail(ctx: MissionContext, result: PhaseResult) -> tuple[bool, str]:
    if result.status == PhaseStatus.SUCCESS and not ctx.person_detected:
        return False, "person_detected not set despite SUCCESS"
    return True, ""


# ======================================================================
# Phase 3: APPROACH_CONFIRM
# ======================================================================

def _approach_confirm_handler(ctx: MissionContext) -> PhaseResult:
    """
    Navigate to detected person, re-detect, confirm it's a real person.
    Demo: always confirms.
    """
    logger.info("  Approaching detected person…")
    _demo_sleep(0.2)

    if ctx.mode == "demo":
        ctx.approach_confirmed = True
        ctx.standoff_established = True
        ctx.person_confidence = 0.92
        ctx.transcript.append({"role": "robot", "text": "I can see you. I'm a rescue robot. I'm here to help."})
    else:
        ctx.approach_confirmed = False

    if not ctx.approach_confirmed:
        return PhaseResult(
            status=PhaseStatus.RETRY,
            reason="Cannot confirm person — may be false positive",
            outputs={"approach_confirmed": False},
        )

    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={
            "approach_confirmed": True,
            "standoff_established": ctx.standoff_established,
            "person_confidence": ctx.person_confidence,
        },
        reason=f"Person confirmed at standoff (conf={ctx.person_confidence:.2f})",
        next_recommendation="Check for debris / hazards before triage.",
    )


def _pre_approach(ctx: MissionContext) -> tuple[bool, str]:
    if not ctx.person_detected:
        return False, "No person detected — cannot approach"
    return True, ""


def _post_approach(ctx: MissionContext, result: PhaseResult) -> tuple[bool, str]:
    if result.status == PhaseStatus.SUCCESS and not ctx.approach_confirmed:
        return False, "approach_confirmed not set"
    return True, ""


# ======================================================================
# Phase 4: DEBRIS_CLEAR
# ======================================================================

def _debris_clear_handler(ctx: MissionContext) -> PhaseResult:
    """
    Assess and attempt to clear debris blocking access.
    Demo: reports minor debris, marks as cleared.
    Failure mode: if debris is immovable, mark status and proceed anyway.
    """
    logger.info("  Scanning for debris and hazards…")
    _demo_sleep(0.2)

    if ctx.mode == "demo":
        ctx.debris_status = "clear"
        ctx.debris_images = [
            _write_evidence(ctx, "images/debris_scan_front.txt", "SIMULATED: no major debris detected"),
        ]
    else:
        ctx.debris_status = "unknown"

    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={
            "debris_status": ctx.debris_status,
            "debris_images": ctx.debris_images,
        },
        evidence={"debris_images": ctx.debris_images},
        reason=f"Debris assessment: {ctx.debris_status}",
        next_recommendation="Proceed to triage dialogue and body scan.",
    )


def _pre_debris(ctx: MissionContext) -> tuple[bool, str]:
    if not ctx.approach_confirmed:
        return False, "Approach not confirmed — cannot assess debris"
    return True, ""


# ======================================================================
# Phase 5: TRIAGE_DIALOG_SCAN
# ======================================================================

def _triage_dialog_scan_handler(ctx: MissionContext) -> PhaseResult:
    """
    Medical triage dialogue + body scan.
    Uses the TriageDialogueManager from dialogue_manager.py.
    Demo: runs a simulated conversation.
    """
    logger.info("  Starting triage dialogue and body scan…")

    try:
        from himpublic.orchestrator.dialogue_manager import TriageDialogueManager
    except ImportError:
        return PhaseResult(
            status=PhaseStatus.FAIL,
            reason="dialogue_manager not available",
        )

    dm = TriageDialogueManager()

    if ctx.mode == "demo":
        # Simulate a realistic multi-turn triage dialogue
        simulated_exchanges = [
            (None, None),  # initial
            ("yes I need help, I'm hurt", "needs_help"),
            ("yes there is bleeding", "major_bleeding"),
            ("in my left leg", "bleeding_location"),
            ("it's heavy, soaking through my clothes", "bleeding_severity"),
            ("yes I can talk clearly", "airway_talking"),
            ("no trouble breathing", "breathing_distress"),
            ("no chest injury", "chest_injury"),
            ("I feel a bit dizzy", "shock_signs"),
            ("no I can move my arms and legs", "trapped_or_cant_move"),
            ("no I didn't hit my head", "head_injury"),
            ("no fire or smoke", "hazards"),
            ("just the leg wound", "other_wounds"),
            ("pain is about 7 out of 10", "pain"),
            ("no I'm not cold", "feeling_cold"),
            ("yes you can take photos", "consent_photos"),
        ]

        now = time.monotonic()
        for victim_text, q_key in simulated_exchanges:
            now += 0.5
            result = dm.process_turn(victim_text, q_key, now)
            # Log transcript
            if result.get("robot_utterance"):
                ctx.transcript.append({"role": "robot", "text": result["robot_utterance"]})
            if victim_text:
                ctx.transcript.append({"role": "victim", "text": victim_text})

        # Simulate image capture
        for view in ("front", "left", "right", "wound_closeup"):
            img_path = _write_evidence(
                ctx, f"images/scan_{view}.txt",
                f"SIMULATED: body scan image from {view} view"
            )
            ctx.scan_images.append(img_path)

        ctx.triage_answers = dm.patient_state.known_slots()
        ctx.patient_state = dm.patient_state.to_dict()

    else:
        # Robot mode: would use audio_io for real dialogue
        r = dm.get_initial_greeting()
        ctx.transcript.append({"role": "robot", "text": r["robot_utterance"]})
        ctx.triage_answers = r.get("triage_answers", {})

    # Save transcript evidence
    transcript_path = _write_evidence(
        ctx, "transcript.json",
        json.dumps(ctx.transcript, indent=2, ensure_ascii=False),
    )

    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={
            "triage_answers": ctx.triage_answers,
            "patient_state": ctx.patient_state,
            "scan_images": ctx.scan_images,
        },
        evidence={
            "transcript": transcript_path,
            "scan_images": ctx.scan_images,
        },
        reason=f"Triage complete — {len(ctx.triage_answers)} slots filled, {len(ctx.scan_images)} images",
        next_recommendation="Compile and send report to command center.",
    )


def _pre_triage(ctx: MissionContext) -> tuple[bool, str]:
    if not ctx.approach_confirmed:
        return False, "Approach not confirmed — cannot start triage"
    return True, ""


def _post_triage(ctx: MissionContext, result: PhaseResult) -> tuple[bool, str]:
    if result.status == PhaseStatus.SUCCESS and not ctx.triage_answers:
        return False, "No triage answers collected"
    return True, ""


# ======================================================================
# Phase 6: REPORT_SEND
# ======================================================================

def _report_send_handler(ctx: MissionContext) -> PhaseResult:
    """
    Compile structured report and send to command center.
    On failure: queue to disk for later retry.
    """
    logger.info("  Compiling and sending incident report…")
    _demo_sleep(0.2)

    incident_id = f"incident_{ctx.run_id}"
    report = {
        "incident_id": incident_id,
        "run_id": ctx.run_id,
        "timestamp": time.time(),
        "patient_summary": ctx.triage_answers,
        "patient_state": ctx.patient_state,
        "location_hint": ctx.person_location_hint,
        "debris_status": ctx.debris_status,
        "images": ctx.scan_images + ctx.debris_images,
        "transcript": ctx.transcript,
        "confidence": ctx.person_confidence,
    }

    # Generate markdown summary
    md_lines = [
        f"# Incident Report: {incident_id}",
        "",
        "## Patient Summary",
    ]
    for k, v in ctx.triage_answers.items():
        md_lines.append(f"- **{k}:** {v}")
    md_lines.extend([
        "",
        f"## Location: {ctx.person_location_hint or 'unknown'}",
        f"## Debris: {ctx.debris_status or 'unknown'}",
        f"## Images captured: {len(ctx.scan_images)}",
        f"## Detection confidence: {ctx.person_confidence:.2f}",
    ])
    report["document"] = "\n".join(md_lines)
    ctx.report_payload = report

    # Attempt to send
    sent = False
    try:
        from himpublic.comms.command_center_client import CommandCenterClient
        import os
        url = os.environ.get("HIMPUBLIC_COMMAND_CENTER_URL", "").strip()
        if url:
            client = CommandCenterClient(url)
            sent = client.post_report(report)
    except Exception as e:
        logger.warning("  Command center send failed: %s — report saved to disk", e)

    # Always save to disk as backup
    report_path = _write_evidence(
        ctx, "report.json",
        json.dumps(report, indent=2, default=str, ensure_ascii=False),
    )
    ctx.report_sent = sent
    ctx.report_path = report_path
    ctx.transcript.append({
        "role": "robot",
        "text": "Report sent to command center." if sent else "Report saved locally. Will retry transmission.",
    })

    # Even if send fails, we have the report on disk → SUCCESS (degraded)
    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={
            "report_sent": sent,
            "report_path": report_path,
            "incident_id": incident_id,
        },
        evidence={"report": report_path},
        reason=f"Report {'sent to CC' if sent else 'saved to disk (CC unavailable)'}",
        next_recommendation="Enter monitoring/wait mode.",
    )


def _pre_report(ctx: MissionContext) -> tuple[bool, str]:
    if not ctx.triage_answers and not ctx.patient_state:
        return False, "No triage data — cannot compile report"
    return True, ""


def _post_report(ctx: MissionContext, result: PhaseResult) -> tuple[bool, str]:
    if not ctx.report_path:
        return False, "report_path not set"
    return True, ""


# ======================================================================
# Phase 7: MONITOR_WAIT
# ======================================================================

def _monitor_wait_handler(ctx: MissionContext) -> PhaseResult:
    """
    Stay with victim, monitor for changes, relay operator messages.
    Demo: immediate success (would block in robot mode).
    """
    logger.info("  Entering monitoring mode — staying with victim…")
    _demo_sleep(0.2)

    ctx.monitor_active = True
    ctx.transcript.append({
        "role": "robot",
        "text": "I'm staying with you. Help is on the way. Tell me if anything changes.",
    })

    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={"monitor_active": True},
        reason="Monitoring mode active — awaiting rescue team arrival",
        next_recommendation="Await rescue team handoff or operator command.",
    )


def _pre_monitor(ctx: MissionContext) -> tuple[bool, str]:
    if not ctx.report_path:
        return False, "Report not generated — cannot enter monitoring"
    return True, ""


# ======================================================================
# Pipeline phase list (THE canonical order)
# ======================================================================

class PipelinePhase:
    """Phase name constants."""
    DEPLOY = "DEPLOY"
    SEARCH_HAIL = "SEARCH_HAIL"
    APPROACH_CONFIRM = "APPROACH_CONFIRM"
    DEBRIS_CLEAR = "DEBRIS_CLEAR"
    TRIAGE_DIALOG_SCAN = "TRIAGE_DIALOG_SCAN"
    REPORT_SEND = "REPORT_SEND"
    MONITOR_WAIT = "MONITOR_WAIT"


PIPELINE_PHASES: list[PhaseDefinition] = [
    PhaseDefinition(
        name=PipelinePhase.DEPLOY,
        label="Deploy / Self-check",
        handler=_deploy_handler,
        retry_policy=RetryPolicy(max_attempts=2, cooldown_s=1.0, allow_degraded=True),
        preconditions=[_pre_deploy],
        postconditions=[_post_deploy],
        announce_text="Booting up. Running self-check.",
    ),
    PhaseDefinition(
        name=PipelinePhase.SEARCH_HAIL,
        label="Search & Hail",
        handler=_search_hail_handler,
        retry_policy=RetryPolicy(max_attempts=5, cooldown_s=2.0, allow_degraded=False,
                                 fallback_status=PhaseStatus.ABORT),
        preconditions=[_pre_search_hail],
        postconditions=[_post_search_hail],
        announce_text="Looking for a person. If anyone can hear me, call out.",
    ),
    PhaseDefinition(
        name=PipelinePhase.APPROACH_CONFIRM,
        label="Approach & Confirm",
        handler=_approach_confirm_handler,
        retry_policy=RetryPolicy(max_attempts=3, cooldown_s=2.0, allow_degraded=False),
        preconditions=[_pre_approach],
        postconditions=[_post_approach],
        announce_text="Person detected. Approaching to confirm.",
    ),
    PhaseDefinition(
        name=PipelinePhase.DEBRIS_CLEAR,
        label="Debris Assessment & Clear",
        handler=_debris_clear_handler,
        retry_policy=RetryPolicy(max_attempts=2, cooldown_s=1.0, allow_degraded=True),
        preconditions=[_pre_debris],
        announce_text="Checking for debris and hazards.",
    ),
    PhaseDefinition(
        name=PipelinePhase.TRIAGE_DIALOG_SCAN,
        label="Triage Dialogue & Body Scan",
        handler=_triage_dialog_scan_handler,
        retry_policy=RetryPolicy(max_attempts=2, cooldown_s=2.0, allow_degraded=True),
        preconditions=[_pre_triage],
        postconditions=[_post_triage],
        announce_text="Starting medical assessment. I will ask a few questions.",
    ),
    PhaseDefinition(
        name=PipelinePhase.REPORT_SEND,
        label="Compile & Send Report",
        handler=_report_send_handler,
        retry_policy=RetryPolicy(max_attempts=3, cooldown_s=3.0, allow_degraded=True),
        preconditions=[_pre_report],
        postconditions=[_post_report],
        announce_text="Compiling report for the command center.",
    ),
    PhaseDefinition(
        name=PipelinePhase.MONITOR_WAIT,
        label="Monitor & Wait",
        handler=_monitor_wait_handler,
        retry_policy=RetryPolicy(max_attempts=1, cooldown_s=0.0),
        preconditions=[_pre_monitor],
        announce_text="Staying with you. Help is on the way.",
    ),
]
