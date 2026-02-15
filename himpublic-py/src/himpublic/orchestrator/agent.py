"""Always-on orchestrator: perception, audio, policy, actuation, telemetry. Clean shutdown on Ctrl+C."""

from __future__ import annotations

import asyncio
import logging
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .config import OrchestratorConfig
from .phases import Phase, PHASE_LABELS, PHASE_ANNOUNCE, parse_phase
from .events import EventManager, EventType
from .policy import Action, Decision, ReflexController, LLMPolicy
from .llm_adapter import propose_action
from .search_phase import (
    SearchForPersonPhase,
    SearchPhaseConfig,
    SearchResult,
    RobotActions as SearchRobotActions,
)
from himpublic.io.robot_interface import RobotInterface
from himpublic.io.mock_robot import MockRobot
from himpublic.io.video_source import BaseVideoSource, WebcamVideoSource, FileVideoSource, RobotVideoSource
from himpublic.io.audio_io import AudioIO, LocalAudioIO, RobotAudioIO
from himpublic.perception.person_detector import PersonDetector, draw_boxes
from himpublic.perception.types import Observation
from himpublic.perception.frame_store import LatestFrameStore, RingBuffer
from himpublic.comms.command_center_client import CommandCenterClient
from himpublic.orchestrator.dialogue_manager import TriageDialogueManager
from himpublic.utils.event_logger import SearchEventLogger

# Medical triage CV pipeline (additive integration)
try:
    from himpublic.medical.triage_pipeline import TriagePipeline as _TriagePipeline
    _MEDICAL_AVAILABLE = True
except ImportError:
    _TriagePipeline = None  # type: ignore[misc, assignment]
    _MEDICAL_AVAILABLE = False

logger = logging.getLogger(__name__)

# LLM decision log file (append JSONL)
LLM_DECISIONS_LOG = "logs/llm_decisions.jsonl"


def _log_llm_decision(
    timestamp: float,
    phase: str,
    obs_summary: dict,
    llm_output: dict | None,
    used_llm: bool,
) -> None:
    """Append one JSON line to logs/llm_decisions.jsonl."""
    import json
    from pathlib import Path
    log_path = Path(LLM_DECISIONS_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": timestamp,
        "phase": phase,
        "obs_summary": obs_summary,
        "llm_output": llm_output,
        "used_llm": used_llm,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


TRIAGE_LOG = "logs/triage.jsonl"


def _log_triage(entry: dict) -> None:
    """Append one JSON line to logs/triage.jsonl."""
    import json
    from pathlib import Path
    log_path = Path(TRIAGE_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_transcript(state: "SharedState", speaker: str, text: str) -> None:
    """Append one transcript turn: 'HH:MM:SS | Speaker: text'."""
    t = (text or "").strip()
    if not t:
        return
    stamp = time.strftime("%H:%M:%S", time.localtime())
    line = f"{stamp} | {speaker}: {t}"
    buf = getattr(state, "conversation_transcript", None)
    if isinstance(buf, list):
        buf.append(line)
        # Keep bounded to avoid unbounded memory growth in long sessions
        if len(buf) > 500:
            del buf[:-500]


def _apply_decision_params(
    state: SharedState,
    decision: Decision,
    now: float,
    cc_client: CommandCenterClient | None = None,
) -> None:
    """Apply decision.params to shared state: triage updates, capture_views, report send, pending-question latch."""
    params = decision.params or {}
    # Reset search sub-phase when entering search_localize from a different phase
    if decision.mode == Phase.SEARCH_LOCALIZE.value and state.phase != Phase.SEARCH_LOCALIZE.value:
        state.search_sub_phase = "announce"
        state.search_ask_retries = 0
    # Clear pending-question state when transitioning to scan_capture
    if decision.mode == Phase.SCAN_CAPTURE.value:
        state.pending_question_id = None
        state.pending_question_text = None
        state.pending_question_asked_at = None
        state.pending_question_retries = 0
        state.pending_followup_key = None
        state.pending_followup_question = None
    if "clear_last_response" in params:
        state.last_response = None
    if "last_answer_acknowledged" in params:
        state.last_answer_acknowledged = bool(params["last_answer_acknowledged"])
    if "clear_pending_question" in params:
        state.pending_question_id = None
        state.pending_question_text = None
        state.pending_question_asked_at = None
        state.pending_question_retries = 0
    if "triage_step_index" in params:
        state.triage_step_index = int(params["triage_step_index"])
    if "triage_answers_delta" in params:
        delta = params["triage_answers_delta"]
        if isinstance(delta, dict):
            state.triage_answers.update(delta)
            if "consent_photos" in delta:
                v = delta["consent_photos"]
                state.consent_for_photos = bool(v) if isinstance(v, bool) else None
            # Use victim's spoken body part for medical pipeline (CV does not infer body part)
            if _MEDICAL_AVAILABLE:
                spoken = (
                    delta.get("injury_location")
                    or delta.get("injury_location_detail")
                    or delta.get("bleeding_location")
                )
                if spoken and getattr(state, "_medical_pipeline_ref", None) is not None:
                    state._medical_pipeline_ref.set_spoken_body_region(str(spoken))
        _log_triage({"timestamp": now, "triage_answers": dict(state.triage_answers), "step_index": state.triage_step_index})
    if "current_question_key" in params:
        state.current_question_key = params["current_question_key"]
    if "pending_followup_key" in params:
        state.pending_followup_key = params["pending_followup_key"]
    if "pending_followup_question" in params:
        state.pending_followup_question = params["pending_followup_question"]
    # Set pending-question latch when we emit ASK (so we WAIT until response or timeout)
    if decision.action == Action.ASK and params.get("set_pending_question") and "pending_question_id" in params:
        state.pending_question_id = params["pending_question_id"]
        state.pending_question_text = params.get("pending_question_text")
        state.pending_question_asked_at = now
        if "pending_question_retries" in params:
            state.pending_question_retries = int(params["pending_question_retries"])
        if "current_question_key" in params:
            state.current_question_key = params["current_question_key"]
    if "last_prompt" in params:
        state.last_prompt = params["last_prompt"]
    # Persist dialogue manager back from conversation_state to SharedState
    if "_dialogue_manager" in params:
        state.dialogue_manager = params["_dialogue_manager"]
    # Send triage update to command center (dedup'd by dialogue manager)
    if params.get("send_triage_update") and "triage_update_payload" in params:
        payload = params["triage_update_payload"]
        if cc_client and getattr(cc_client, "_enabled", False):
            try:
                cc_client.post_event(payload)
            except Exception as e:
                logger.warning("Command center triage update failed: %s", e)
    # Search sub-phase tracking
    if "search_sub_phase" in params:
        state.search_sub_phase = str(params["search_sub_phase"])
    if "search_ask_retries" in params:
        state.search_ask_retries = int(params["search_ask_retries"])
    if "capture_views" in params:
        from himpublic.orchestrator.placeholders import capture_image
        views = params["capture_views"]
        if isinstance(views, (list, tuple)):
            for view in views:
                try:
                    img_id = capture_image(str(view))
                    state.images_captured.append(img_id)
                except Exception as e:
                    logger.warning("capture_image(%s) failed: %s", view, e)
        _log_triage({"timestamp": now, "images_captured": list(state.images_captured)})
    if params.get("send_report") and "report_payload" in params:
        report_payload = params["report_payload"]
        sent = False
        if cc_client and getattr(cc_client, "_enabled", False):
            try:
                sent = cc_client.post_report(report_payload)
            except Exception as e:
                logger.warning("Command center post_report failed: %s", e)
        if not sent:
            try:
                from himpublic.orchestrator.placeholders import send_to_command_center
                send_to_command_center(report_payload)
                sent = True
            except Exception as e:
                logger.warning("send_to_command_center failed: %s", e)
        state.report_sent = sent
        if sent:
            logger.info(
                "Incident report document created and sent to command center: incident_id=%s",
                report_payload.get("incident_id"),
            )
        _log_triage({"timestamp": now, "report_sent": state.report_sent, "report_payload": report_payload})

    # Medical triage report generation (additive — triggers alongside existing report)
    # Build report when we have CV findings OR triage answers (speech-first: victim Q&A still produces a report)
    if params.get("send_report") and _MEDICAL_AVAILABLE:
        _medical_pipeline = getattr(state, "_medical_pipeline_ref", None)
        triage_answers = dict(getattr(state, "triage_answers", {}))
        should_build = (
            _medical_pipeline is not None
            and (_medical_pipeline.has_significant_findings or triage_answers)
        )
        if should_build:
            try:
                # Use victim's spoken body part (e.g. "my knee") for report
                spoken_region = (
                    triage_answers.get("injury_location")
                    or triage_answers.get("injury_location_detail")
                    or triage_answers.get("bleeding_location")
                )
                if not spoken_region and isinstance(triage_answers.get("pain_locations"), list):
                    pl = triage_answers["pain_locations"]
                    spoken_region = pl[0] if pl else None
                if spoken_region:
                    _medical_pipeline.set_spoken_body_region(str(spoken_region))
                transcript_lines = list(getattr(state, "conversation_transcript", []))
                report_path = _medical_pipeline.build_report(
                    scene_summary="Automated triage assessment by rescue robot.",
                    victim_answers=triage_answers,
                    notes=[
                        "Generated during REPORT_SEND phase.",
                        f"Transcript turns captured: {len(transcript_lines)}.",
                    ],
                    conversation_transcript=transcript_lines,
                    meta={"session_id": params.get("report_payload", {}).get("incident_id", "")},
                )
                if report_path:
                    logger.info("Medical triage report saved to %s", report_path)
                    try:
                        abs_path = str(Path(report_path).resolve())
                        print(f"[Report saved] {abs_path}", flush=True)
                    except Exception:
                        print(f"[Report saved] {report_path}", flush=True)
            except Exception as e:
                logger.warning("Medical triage report generation failed: %s", e)


def _format_decision_debug(
    phase: str,
    obs_summary: dict,
    heard: str | None,
    decision: Decision,
) -> str:
    """One-line summary for debugging: camera + heard -> decision."""
    n = obs_summary.get("num_persons", 0)
    conf = obs_summary.get("confidence", 0)
    camera = f"persons={n} conf={conf:.2f}"
    heard_str = repr(heard) if heard else "None"
    action = decision.action.value if hasattr(decision.action, "value") else str(decision.action)
    say = decision.say or "—"
    wait_s = decision.wait_for_response_s if decision.wait_for_response_s is not None else "—"
    llm = " [LLM]" if getattr(decision, "used_llm", False) else ""
    return (
        f"[DECISION] phase={phase} | camera: {camera} | heard: {heard_str} | "
        f"-> action={action} say={say[:40] + '…' if say != '—' and len(say) > 40 else say} listen_s={wait_s} mode={decision.mode}{llm}"
    )


def _create_robot(config: OrchestratorConfig) -> RobotInterface:
    if config.robot_adapter == "mock":
        return MockRobot(search_iterations_to_detect=config.mock_search_iterations_to_detect)
    if config.robot_adapter == "booster":
        from himpublic.io.booster_adapter import BoosterAdapter
        return BoosterAdapter()
    if config.robot_adapter == "ros2":
        from himpublic.io.ros2_bridge import Ros2Bridge
        return Ros2Bridge()
    raise ValueError(f"Unknown robot_adapter: {config.robot_adapter}")


def _create_video_source(config: OrchestratorConfig) -> BaseVideoSource | None:
    if config.video_mode == "webcam":
        return WebcamVideoSource(index=config.webcam_index)
    if config.video_mode == "file":
        if not config.video_path:
            raise ValueError("--video-path required when --video file")
        return FileVideoSource(path=config.video_path)
    if config.video_mode == "robot":
        return RobotVideoSource()
    return None


def _create_audio_io(config: OrchestratorConfig) -> AudioIO:
    if config.io_mode == "local":
        return LocalAudioIO(use_tts=config.use_tts, use_mic=config.use_mic)
    if config.io_mode == "robot":
        return RobotAudioIO()
    return LocalAudioIO(use_tts=config.use_tts, use_mic=config.use_mic)


# Simulated map bounds (match webapp floor plan SVG: 604x320)
MAP_W = 604
MAP_H = 320
VICTIM_MAP_X = 68
VICTIM_MAP_Y = 58


def _mic_level_thread(state: SharedState, stop_event: asyncio.Event) -> None:
    """Background thread: read mic input and set state._mic_level (0.0–1.0) for the preview meter."""
    import math
    try:
        import pyaudio
    except ImportError:
        return
    CHUNK = 1024
    RATE = 16000
    FORMAT = pyaudio.paInt16
    # Normalize: RMS above this maps to 1.0 (tune so normal speech fills the bar)
    RMS_CAP = 2000.0
    p = pyaudio.PyAudio()
    try:
        stream = p.open(format=FORMAT, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
    except Exception as e:
        logger.debug("Mic level meter: could not open input stream: %s", e)
        p.terminate()
        return
    try:
        while not stop_event.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                count = len(data) // 2
                if count == 0:
                    continue
                samples = struct.unpack_from(f"{count}h", data)
                rms = math.sqrt(sum(s * s for s in samples) / count)
                level = min(1.0, rms / RMS_CAP)
                state._mic_level = level
            except Exception as e:
                logger.debug("Mic level read: %s", e)
                state._mic_level = 0.0
            time.sleep(0.05)
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        p.terminate()


@dataclass
class SharedState:
    """State shared between agent tasks. Uses Phase for high-level mission phase."""
    observation: Observation | None = None
    decision: Decision | None = None
    # Debug / introspection (for command center)
    last_decision_summary: dict | None = None  # json-safe summary of last decision
    last_llm_proposal: dict | None = None  # raw LLM adapter output (should be json-safe)
    phase: str = Phase.SEARCH_LOCALIZE.value  # current Phase.value
    phase_entered_at: float | None = None
    boot_ready: bool = False
    degraded_mode: bool = False  # e.g. no depth sensor
    last_response: str | None = None
    last_asked_at: float | None = None
    last_speak_done: float = 0.0  # monotonic time when TTS finished (so audio_loop can wait 3s before listen)
    last_prompt: str | None = None  # last triage question/phrase we said
    person_found_emitted: bool = False
    wait_for_response_until: float | None = None
    # Triage / report flow (ASSIST_COMMUNICATE → SCAN_CAPTURE → REPORT_SEND)
    triage_step_index: int = 0
    triage_answers: dict = field(default_factory=dict)  # key -> parsed value
    consent_for_photos: bool | None = None
    images_captured: list = field(default_factory=list)  # list of path/id strings
    report_sent: bool = False
    pending_phase_announcement: str | None = None  # speak this once (phase status out loud)
    # No response after 2 repeats → assume victim cannot talk, proceed with visual inspection only
    no_response_count: int = 0
    assume_cannot_talk: bool = False
    # Pending-question latch: only ASK once per question, then WAIT until response or timeout
    pending_question_id: str | None = None
    pending_question_text: str | None = None
    pending_question_asked_at: float | None = None
    pending_question_retries: int = 0
    last_answer_acknowledged: bool = False
    current_question_key: str | None = None  # key we are collecting answer for (step or followup)
    # Body-part followup: insert one question before continuing triage
    pending_followup_key: str | None = None
    pending_followup_question: str | None = None
    # Search sub-phase state (within SEARCH_LOCALIZE)
    search_sub_phase: str = "announce"  # announce → ask_location → basic_search
    search_ask_retries: int = 0
    # Slot-based dialogue manager (persists across policy ticks)
    dialogue_manager: TriageDialogueManager | None = None
    # Full transcript for report (robot + victim turns)
    conversation_transcript: list[str] = field(default_factory=list)
    # Mic level 0.0–1.0 for preview meter (updated by background thread)
    _mic_level: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def set_debug_payload(self, decision_summary: dict | None, llm_proposal: dict | None) -> None:
        async with self._lock:
            self.last_decision_summary = decision_summary
            self.last_llm_proposal = llm_proposal

    async def get_debug_payload(self) -> dict:
        async with self._lock:
            return {
                "decision": self.last_decision_summary,
                "llm_proposal": self.last_llm_proposal,
                "last_response": self.last_response,
                "last_prompt": self.last_prompt,
                "pending_question_id": self.pending_question_id,
                "pending_question_text": self.pending_question_text,
                "pending_question_retries": self.pending_question_retries,
                "search_sub_phase": self.search_sub_phase,
                "search_ask_retries": self.search_ask_retries,
            }

    async def set_observation(self, obs: Observation | None) -> None:
        async with self._lock:
            self.observation = obs

    async def get_observation(self) -> Observation | None:
        async with self._lock:
            return self.observation

    async def set_decision(self, d: Decision | None) -> None:
        async with self._lock:
            self.decision = d

    async def get_decision(self) -> Decision | None:
        async with self._lock:
            return self.decision

    async def set_phase(self, p: str) -> None:
        async with self._lock:
            self.phase = p

    async def get_phase(self) -> str:
        async with self._lock:
            return self.phase

    async def set_mode(self, m: str) -> None:
        """Legacy: set phase (mode and phase are the same)."""
        async with self._lock:
            self.phase = m

    async def get_mode(self) -> str:
        """Legacy: return phase."""
        async with self._lock:
            return self.phase

    def conversation_state(self) -> dict:
        return {
            "phase": self.phase,
            "mode": self.phase,
            "last_asked_at": self.last_asked_at,
            "last_response": self.last_response,
            "last_prompt": self.last_prompt,
            "boot_ready": self.boot_ready,
            "degraded_mode": self.degraded_mode,
            "phase_entered_at": self.phase_entered_at,
            "triage_step_index": self.triage_step_index,
            "triage_answers": dict(self.triage_answers),
            "consent_for_photos": self.consent_for_photos,
            "images_captured": list(self.images_captured),
            "report_sent": self.report_sent,
            "no_response_count": self.no_response_count,
            "assume_cannot_talk": self.assume_cannot_talk,
            "pending_question_id": self.pending_question_id,
            "pending_question_text": self.pending_question_text,
            "pending_question_asked_at": self.pending_question_asked_at,
            "pending_question_retries": self.pending_question_retries,
            "last_answer_acknowledged": self.last_answer_acknowledged,
            "current_question_key": self.current_question_key,
            "pending_followup_key": self.pending_followup_key,
            "pending_followup_question": self.pending_followup_question,
            "search_sub_phase": self.search_sub_phase,
            "search_ask_retries": self.search_ask_retries,
            "conversation_transcript": list(self.conversation_transcript),
            # Dialogue manager reference (policy.py reads/creates this)
            "_dialogue_manager": self.dialogue_manager,
            # Medical triage CV findings summary (additive — populated by _medical_triage_loop)
            "_medical_findings_summary": getattr(self, "_medical_findings_summary", None),
        }


class OrchestratorAgent:
    """Always-on agent: perception, audio, policy, actuation, telemetry. Runs until stop requested."""

    def __init__(self, config: OrchestratorConfig) -> None:
        self.config = config
        self._stop_event = asyncio.Event()
        self._state = SharedState()
        self._video_source: BaseVideoSource | None = None
        self._audio_io: AudioIO | None = None
        self._robot: RobotInterface | None = None
        self._person_detector: PersonDetector | None = None
        self._frame_store: LatestFrameStore | None = None
        self._ring_buffer: RingBuffer | None = None
        self._event_manager: EventManager | None = None
        self._cc_client: CommandCenterClient | None = None
        self._reflex = ReflexController()
        self._llm_policy = LLMPolicy()
        self._tasks: list[asyncio.Task] = []
        # Simulated robot position on map (for command center /latest)
        self._sim_map_x = 300.0
        self._sim_map_y = 160.0
        # Operator messages already spoken (indices) so we don't repeat
        self._operator_messages_spoken_through_index: int = -1

        # Medical triage CV pipeline (additive — no existing code changed)
        self._medical_pipeline: _TriagePipeline | None = None  # type: ignore[valid-type]
        if _MEDICAL_AVAILABLE:
            try:
                self._medical_pipeline = _TriagePipeline(
                    output_dir="reports",
                    evidence_dir="reports/evidence",
                    use_pose=True,
                )
                # Store ref on SharedState so _apply_decision_params can build report
                self._state._medical_pipeline_ref = self._medical_pipeline  # type: ignore[attr-defined]
                logger.info("Medical triage pipeline initialised.")
            except Exception as e:
                logger.warning("Medical triage pipeline init failed: %s", e)
                self._medical_pipeline = None

        if config.io_mode == "robot":
            # Robot mode: use Robot Bridge server for camera, audio, and (gated) motion.
            from himpublic.io.robot_client import RobotBridgeClient, BridgeVideoSource, BridgeAudioIO
            bridge = RobotBridgeClient(base_url=config.robot_bridge_url)
            self._video_source = BridgeVideoSource(bridge)
            self._audio_io = BridgeAudioIO(bridge, use_local_asr=config.use_mic)
            # Detect rubble via open-vocab YOLO-World + QR + COCO fallback
            search_target = getattr(config, "search_target", "rubble")
            rubble_prompts = list(getattr(config, "rubble_prompts", []))
            self._person_detector = PersonDetector(
                model_path=config.yolo_model,
                threshold=config.detection_threshold,
                target=search_target,
                rubble_prompts=rubble_prompts or None,
            )
            self._frame_store = LatestFrameStore()
            self._ring_buffer = RingBuffer(
                max_seconds=config.ring_seconds,
                fps_sample=config.ring_fps,
            )
            self._cc_client = CommandCenterClient(config.command_center_url)
            self._event_manager = EventManager(
                ring_buffer=self._ring_buffer,
                client=self._cc_client,
                snapshots_dir="data/snapshots",
                keyframe_seconds_back=5.0,
                keyframe_count=3,
                heartbeat_snapshot_interval_s=config.save_heartbeat_seconds,
            )
            self._bridge_client = bridge  # keep reference for state/motion
            logger.info("IO mode: ROBOT (bridge at %s)", config.robot_bridge_url)
        elif config.io_mode == "local":
            self._video_source = _create_video_source(config)
            self._audio_io = _create_audio_io(config)
            search_target = getattr(config, "search_target", "rubble")
            rubble_prompts = list(getattr(config, "rubble_prompts", []))
            self._person_detector = PersonDetector(
                model_path=config.yolo_model,
                threshold=config.detection_threshold,
                target=search_target,
                rubble_prompts=rubble_prompts or None,
            )
            self._frame_store = LatestFrameStore()
            self._ring_buffer = RingBuffer(
                max_seconds=config.ring_seconds,
                fps_sample=config.ring_fps,
            )
            self._cc_client = CommandCenterClient(config.command_center_url)
            self._event_manager = EventManager(
                ring_buffer=self._ring_buffer,
                client=self._cc_client,
                snapshots_dir="data/snapshots",
                keyframe_seconds_back=5.0,
                keyframe_count=3,
                heartbeat_snapshot_interval_s=config.save_heartbeat_seconds,
            )
        else:
            self._robot = _create_robot(config)

    def request_stop(self) -> None:
        self._stop_event.set()

    async def _boot_check(self) -> None:
        """Self-check: verify sensors (video, optional mic/comms). Set boot_ready / degraded_mode, then phase. Or start in --start-phase."""
        if self.config.start_phase:
            p = parse_phase(self.config.start_phase)
            self._state.phase = p.value
            self._state.phase_entered_at = time.monotonic()
            self._state.boot_ready = True
            self._state.degraded_mode = False
            self._state.pending_phase_announcement = PHASE_ANNOUNCE.get(p, p.value)
            logger.info("Phase: %s – %s (start-phase demo, boot skipped)", p.value, PHASE_LABELS.get(p, p.value))
            return
        self._state.phase = Phase.BOOT.value
        self._state.phase_entered_at = time.monotonic()
        logger.info("Phase: %s – %s", Phase.BOOT.value, PHASE_LABELS.get(Phase.BOOT, "Boot / Self-check"))
        video_ok = False
        if self._video_source is not None:
            loop = asyncio.get_event_loop()
            frame = await loop.run_in_executor(None, self._video_source.read)
            video_ok = frame is not None
            if not video_ok:
                logger.warning("Boot: video source returned no frame (degraded)")
        elif self._robot is not None:
            try:
                _ = self._robot.get_rgbd_frame()
                video_ok = True
            except Exception as e:
                logger.warning("Boot: robot frame check failed: %s (degraded)", e)
        self._state.boot_ready = video_ok
        self._state.degraded_mode = not video_ok
        self._state.phase = Phase.SEARCH_LOCALIZE.value
        self._state.phase_entered_at = time.monotonic()
        self._state.pending_phase_announcement = PHASE_ANNOUNCE.get(Phase.SEARCH_LOCALIZE, "Scanning for rubble.")
        logger.info("Phase: %s – %s (ready=%s, degraded=%s)",
                    Phase.SEARCH_LOCALIZE.value, PHASE_LABELS.get(Phase.SEARCH_LOCALIZE, "Search"),
                    self._state.boot_ready, self._state.degraded_mode)

    def _build_search_phase_config(self) -> SearchPhaseConfig:
        """Build SearchPhaseConfig from the orchestrator config."""
        mode = "robot" if self.config.io_mode == "robot" else "demo"
        return SearchPhaseConfig(
            audio_step_degrees=self.config.search_audio_step_deg,
            audio_window_s=getattr(self.config, "search_audio_window_s", 0.4),
            audio_delay_between_steps_s=getattr(self.config, "search_audio_delay_s", 0.5),
            audio_min_confidence=self.config.search_audio_min_confidence,
            max_audio_retries=self.config.search_max_audio_retries,
            detection_threshold=self.config.detection_threshold,
            yolo_model=self.config.yolo_model,
            vision_confirm_timeout_s=getattr(self.config, "search_vision_confirm_timeout_s", 10.0),
            approach_person_area_target=self.config.search_approach_area_target,
            approach_timeout_s=getattr(self.config, "search_approach_timeout_s", 30.0),
            no_detection_rescan_s=getattr(self.config, "search_no_detection_rescan_s", 8.0),
            evidence_dir=self.config.search_evidence_dir,
            mode=mode,
            use_tts=self.config.use_tts,
        )

    async def _run_search_phase(self) -> SearchResult | None:
        """Run the SearchForPersonPhase as first phase in SEARCH_LOCALIZE.

        Runs in a thread executor so it doesn't block the async event loop.
        Returns SearchResult or None if skipped.
        """
        phase = await self._state.get_phase()
        if phase != Phase.SEARCH_LOCALIZE.value:
            return None

        # Skip the blocking search phase — use the perception loop + policy instead
        # (The old SearchForPersonPhase was for audio-based person search.
        #  For rubble search, we rely on the YOLO perception loop to detect objects.)
        logger.info("Rubble search mode: skipping blocking SearchForPersonPhase, using perception loop + policy")
        return None  # No blocking search result

        return result

    async def _perception_loop(self) -> None:
        """Read frames, run YOLO, update store + ring, emit FOUND_PERSON on first confident detection."""
        if self._video_source is None or self._person_detector is None or self._frame_store is None or self._ring_buffer is None or self._event_manager is None:
            return
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            frame = await loop.run_in_executor(None, self._video_source.read)
            if frame is None:
                logger.warning("Perception: end of video stream")
                await asyncio.sleep(0.1)
                continue
            phase = self._state.phase
            obs = await loop.run_in_executor(
                None,
                lambda f=frame, p=phase: self._person_detector.observe(f, p),
            )
            self._frame_store.update(frame, obs)
            self._ring_buffer.push(frame, obs)
            await self._state.set_observation(obs)
            if obs.persons and obs.confidence >= self.config.detection_threshold:
                if not self._state.person_found_emitted:
                    self._state.person_found_emitted = True
                    det_names = [d.cls_name for d in obs.persons[:3]]
                    await loop.run_in_executor(
                        None,
                        lambda: self._event_manager.emit(
                            EventType.FOUND_PERSON,
                            {"num_detections": len(obs.persons), "confidence": obs.confidence, "classes": det_names},
                        ),
                    )
            await asyncio.sleep(0.02)

    async def _audio_loop(self) -> None:
        """When in WAIT_FOR_RESPONSE (decision.wait_for_response_s), listen immediately so you can speak during or after the robot."""
        if self._audio_io is None:
            return
        while not self._stop_event.is_set():
            decision = await self._state.get_decision()
            wait_s = decision.wait_for_response_s if decision else None
            if wait_s is not None and wait_s > 0:
                # Listen right away (in parallel with TTS) so user can talk while robot is talking or right after
                print("[Listening now — you can speak during or after the question]", flush=True)
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: self._audio_io.listen(wait_s),
                )
                transcript = (raw or "").strip() or None
                if transcript:
                    self._state.last_response = transcript
                    _append_transcript(self._state, "Victim", transcript)
                    self._state.no_response_count = 0
                    if self._event_manager:
                        await loop.run_in_executor(
                            None,
                            lambda: self._event_manager.emit(
                                EventType.HEARD_RESPONSE,
                                {"transcript": transcript},
                            ),
                        )
                else:
                    # No response (timeout or empty): after 2 repeats assume cannot talk, visual only
                    self._state.no_response_count = getattr(
                        self._state, "no_response_count", 0
                    ) + 1
                    if self._state.no_response_count >= 2:
                        self._state.assume_cannot_talk = True
                        logger.info(
                            "No response after %d attempts — assuming victim cannot talk; proceeding with visual inspection only.",
                            self._state.no_response_count,
                        )
                await self._state.set_decision(None)
                self._state.last_speak_done = 0.0
            await asyncio.sleep(0.2)

    async def _policy_loop(self) -> None:
        """At llm_hz: read obs + conversation_state, optionally get LLM proposal (in executor), call LLMPolicy, set decision + mode."""
        interval = 1.0 / self.config.llm_hz if self.config.llm_hz > 0 else 1.0
        loop = asyncio.get_event_loop()
        tick = 0
        llm_every_n = getattr(self.config, "llm_every_n_ticks", 3)
        llm_stuck_s = getattr(self.config, "llm_stuck_seconds", 5.0)
        api_key = (getattr(self.config, "openai_api_key", "") or "").strip() or None

        while not self._stop_event.is_set():
            obs = await self._state.get_observation()
            conv = self._state.conversation_state()
            now = time.monotonic()
            conv["now"] = now
            phase = conv.get("phase") or conv.get("mode") or Phase.SEARCH_LOCALIZE.value
            phase_entered_at = conv.get("phase_entered_at") or 0.0

            llm_proposal = None
            use_llm_planner = getattr(self.config, "use_llm_planner", False)

            if use_llm_planner and api_key:
                try:
                    from himpublic.planner import (
                        build_world_state,
                        plan_next_actions,
                        validate_plan,
                        plan_to_decision,
                        dispatch_action,
                    )
                    from himpublic.planner.executor import DISPATCH_ONLY_TOOLS
                    ws = build_world_state(
                        phase=phase,
                        observation=obs,
                        conversation_state=conv,
                        tick=tick,
                        last_action=(self._state.decision.action.value if self._state.decision else None),
                        heard_voice=bool(conv.get("last_response")),
                    )
                    logger.info("[STATE] phase=%s persons=%d rubble=%d heard=%s", phase,
                        len(ws.vision.get("persons", [])), len(ws.vision.get("rubble", [])),
                        ws.audio.get("heard_voice"))
                    plan = await loop.run_in_executor(
                        None,
                        lambda: plan_next_actions(ws, api_key=api_key),
                    )
                    ok, validated, errors = validate_plan(plan, phase)
                    if errors:
                        logger.warning("[PLANNER] validation: %s", errors)
                    result = plan_to_decision(plan, validated)
                    decision = result["decision"]
                    remaining = result.get("remaining_actions", [])
                    first_action = validated[0] if validated else None
                    if first_action and first_action.tool in DISPATCH_ONLY_TOOLS:
                        ctx = {"robot": self._robot, "audio_io": self._audio_io, "cc_client": self._cc_client}
                        res = dispatch_action(first_action, ctx)
                        logger.info("[EXEC] %s -> %s", first_action.tool, res.get("ok", False))
                    llm_proposal = {"plan": plan.intent, "actions": [a.tool for a in validated]}
                except Exception as e:
                    logger.warning("[PLANNER] planner failed, falling back to FSM: %s", e)
                    use_llm_planner = False

            if not use_llm_planner:
                if api_key:
                    use_llm_search = phase == Phase.SEARCH_LOCALIZE.value and (
                        (tick % llm_every_n == 0) or (phase_entered_at and (now - phase_entered_at) > llm_stuck_s)
                    )
                    use_llm_assist = phase == Phase.ASSIST_COMMUNICATE.value
                    if use_llm_search or use_llm_assist:
                        try:
                            llm_proposal = await loop.run_in_executor(
                                None,
                                lambda: propose_action(obs, conv, api_key=api_key),
                            )
                        except Exception as e:
                            logger.debug("LLM proposal failed: %s", e)

                decision = self._llm_policy.decide(obs, conv, llm_proposal=llm_proposal)
            # Persist dialogue manager back from conv dict to SharedState (policy.py may create it)
            if conv.get("_dialogue_manager") is not None:
                self._state.dialogue_manager = conv["_dialogue_manager"]
            # Don't overwrite decision with WAIT while we're waiting for a response; keep ASK so audio_loop keeps listening
            keeping_ask = (
                phase == Phase.ASSIST_COMMUNICATE.value
                and decision.action == Action.WAIT
                and conv.get("pending_question_id")
                and not conv.get("last_response")
            )
            if not keeping_ask:
                await self._state.set_decision(decision)
            elif getattr(self.config, "debug_decisions", False):
                logger.debug("assist_communicate: keeping previous ASK decision (waiting for response); not re-emitting ASK")

            # Publish a json-safe effective decision + LLM proposal for command center debugging
            effective = await self._state.get_decision() or decision
            try:
                action_str = effective.action.value if hasattr(effective.action, "value") else str(effective.action)
            except Exception:
                action_str = str(getattr(effective, "action", ""))
            decision_summary = {
                "action": action_str,
                "mode": effective.mode,
                "say": effective.say,
                "wait_for_response_s": effective.wait_for_response_s,
                "used_llm": bool(getattr(effective, "used_llm", False)),
                "params": effective.params or {},
            }
            await self._state.set_debug_payload(decision_summary, llm_proposal)
            await self._state.set_phase(decision.mode)
            await self._state.set_mode(decision.mode)
            if decision.mode != phase:
                self._state.phase_entered_at = now
                # Queue spoken phase announcement for actuation loop
                p = parse_phase(decision.mode)
                self._state.pending_phase_announcement = PHASE_ANNOUNCE.get(p, decision.mode)
            if self._state.phase_entered_at is None:
                self._state.phase_entered_at = now

            # Apply decision params (triage state, capture, report send)
            _apply_decision_params(self._state, decision, now, self._cc_client)

            # Exit gracefully when we reach DONE so user doesn't need Ctrl+C
            if decision.mode == Phase.DONE.value:
                self.request_stop()

            obs_summary = {"num_persons": len(obs.persons) if obs else 0, "confidence": getattr(obs, "confidence", 0) if obs else 0, "phase": phase}
            _log_llm_decision(now, phase, obs_summary, llm_proposal, getattr(decision, "used_llm", False))

            heard = conv.get("last_response")
            decision_line = _format_decision_debug(phase, obs_summary, heard, decision)
            logger.info(decision_line)
            if getattr(self.config, "debug_decisions", False):
                print(decision_line, flush=True)

            tick += 1
            await asyncio.sleep(interval)

    async def _actuation_loop(self) -> None:
        """~10 Hz: reflex override, then apply action to robot / SAY via AudioIO."""
        if self._robot is not None:
            while not self._stop_event.is_set():
                obs = await self._state.get_observation()
                override = self._reflex.override(obs)
                decision = await self._state.get_decision()
                action = override if override is not None else (decision.action if decision else Action.WAIT)
                if action == Action.STOP:
                    self._robot.stop()
                elif action == Action.ROTATE_LEFT:
                    self._robot.set_velocity(0.0, 0.5)
                elif action == Action.ROTATE_RIGHT:
                    self._robot.set_velocity(0.0, -0.5)
                elif action == Action.FORWARD_SLOW:
                    self._robot.set_velocity(0.2, 0.0)
                else:
                    self._robot.stop()
                await asyncio.sleep(0.1)
            self._robot.stop()
            return
        # Local/Robot: AudioIO for SAY/ASK, wave + motion via bridge. Post robot_said and robot_status to command center.
        last_spoke: str | None = None
        last_wave_phase: str | None = None  # track wave to avoid repeating
        bridge = getattr(self, "_bridge_client", None)
        while not self._stop_event.is_set():
            # Post phase to comms chat only (do not speak phase out loud)
            pending = self._state.pending_phase_announcement
            if pending:
                self._state.pending_phase_announcement = None
                phase = self._state.phase
                if self._cc_client and self._cc_client._enabled:
                    self._cc_client.post_event({
                        "event": "robot_status",
                        "status": pending,
                        "stage": phase,
                        "phase_label": PHASE_LABELS.get(parse_phase(phase), phase),
                        "text": pending,
                    })
            decision = await self._state.get_decision()

            # Robot bridge: apply motion (velocity/stop) so robot can "run to where it hears them" and approach
            if bridge is not None and decision is not None:
                obs = await self._state.get_observation()
                override = self._reflex.override(obs)
                action = override if override is not None else decision.action
                loop = asyncio.get_event_loop()
                if action == Action.STOP:
                    await loop.run_in_executor(None, bridge.stop)
                elif action == Action.ROTATE_LEFT:
                    await loop.run_in_executor(None, lambda: bridge.set_velocity(0.0, 0.5))
                elif action == Action.ROTATE_RIGHT:
                    await loop.run_in_executor(None, lambda: bridge.set_velocity(0.0, -0.5))
                elif action == Action.FORWARD_SLOW:
                    await loop.run_in_executor(None, lambda: bridge.set_velocity(0.2, 0.0))
                elif action not in (Action.WAVE, Action.SAY, Action.ASK, Action.WAIT):
                    await loop.run_in_executor(None, bridge.stop)

            # Handle WAVE action: trigger robot hand wave via bridge
            if decision and decision.action == Action.WAVE:
                wave_key = f"{self._state.phase}_{decision.params.get('search_sub_phase', '')}"
                if wave_key != last_wave_phase:
                    last_wave_phase = wave_key
                    # Speak first if there's something to say
                    if decision.say and decision.say != last_spoke:
                        if self._audio_io:
                            self._audio_io.speak(decision.say)
                        _append_transcript(self._state, "Robot", decision.say)
                        if self._cc_client and self._cc_client._enabled:
                            self._cc_client.post_event({"event": "robot_said", "text": decision.say})
                        last_spoke = decision.say
                    # Execute wave via bridge
                    bridge = getattr(self, "_bridge_client", None)
                    if bridge is not None:
                        wave_hand = decision.params.get("wave_hand", "right")
                        wave_cycles = int(decision.params.get("wave_cycles", 2))
                        logger.info("Executing WAVE: hand=%s cycles=%d", wave_hand, wave_cycles)
                        loop = asyncio.get_event_loop()
                        ok = await loop.run_in_executor(
                            None,
                            lambda: bridge.wave(hand=wave_hand, cycles=wave_cycles),
                        )
                        if self._cc_client and self._cc_client._enabled:
                            self._cc_client.post_event({
                                "event": "robot_action",
                                "action": "wave",
                                "hand": wave_hand,
                                "cycles": wave_cycles,
                                "success": ok,
                            })
                        logger.info("WAVE result: %s", "ok" if ok else "failed")
                    else:
                        logger.info("WAVE action (no bridge — demo mode)")

            elif decision and decision.say and decision.say != last_spoke:
                if self._audio_io:
                    self._audio_io.speak(decision.say)
                _append_transcript(self._state, "Robot", decision.say)
                self._state.last_speak_done = time.monotonic()
                if self._cc_client and self._cc_client._enabled:
                    self._cc_client.post_event({"event": "robot_said", "text": decision.say})
                last_spoke = decision.say
                if decision.wait_for_response_s is not None:
                    self._state.last_asked_at = time.monotonic()
            if decision is None:
                last_spoke = None
                last_wave_phase = None
            await asyncio.sleep(0.1)

    async def _medical_triage_loop(self) -> None:
        """Run medical triage CV assessment alongside perception when in relevant phases.

        Additive loop — reads frames from frame_store, runs MedicalAssessor,
        collects evidence, and stores findings on SharedState for policy/report use.
        """
        if self._medical_pipeline is None or self._frame_store is None:
            return
        loop = asyncio.get_event_loop()
        assess_interval = 0.5  # assess at ~2 Hz (lighter than perception)
        _TRIAGE_PHASES = {
            Phase.INJURY_DETECTION.value,
            Phase.ASSIST_COMMUNICATE.value,
            Phase.SCAN_CAPTURE.value,
        }

        while not self._stop_event.is_set():
            phase = self._state.phase

            # Push every frame into evidence buffer (lightweight)
            frame, obs = self._frame_store.get_latest()
            if frame is not None:
                self._medical_pipeline.push_frame(frame)

            # Only run full assessment in triage-relevant phases
            if phase in _TRIAGE_PHASES and frame is not None:
                findings = await loop.run_in_executor(
                    None,
                    lambda f=frame: self._medical_pipeline.assess(f),
                )

                # If significant findings detected, collect evidence once
                if self._medical_pipeline.has_significant_findings:
                    if not getattr(self._state, "_medical_evidence_collected", False):
                        evidence_dir = await loop.run_in_executor(
                            None,
                            lambda: self._medical_pipeline.collect_evidence(),
                        )
                        if evidence_dir:
                            self._state._medical_evidence_collected = True  # type: ignore[attr-defined]
                            logger.info("Medical evidence collected to %s", evidence_dir)

                    # Post findings summary to command center + store on SharedState for policy
                    summary = self._medical_pipeline.findings_summary()
                    self._state._medical_findings_summary = summary  # type: ignore[attr-defined]
                    if self._cc_client and self._cc_client._enabled:
                        try:
                            self._cc_client.post_event({
                                "event": "medical_findings",
                                "phase": phase,
                                **summary,
                            })
                        except Exception:
                            pass

            await asyncio.sleep(assess_interval)

    async def _preview_loop(self) -> None:
        """Show live camera + phase/detection overlay when show_preview enabled. 'q' in window requests stop."""
        if not getattr(self.config, "show_preview", False) or self._frame_store is None:
            return
        while not self._stop_event.is_set():
            frame, obs = self._frame_store.get_latest()
            if frame is None:
                await asyncio.sleep(0.1)
                continue
            if obs and obs.persons:
                frame = draw_boxes(frame, obs.persons)
            phase = self._state.phase
            label = PHASE_LABELS.get(parse_phase(phase), phase)
            cv2.putText(frame, f"Phase: {phase}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, label[:40], (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            n = len(obs.persons) if obs else 0
            cv2.putText(frame, f"Persons: {n}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
            cv2.putText(frame, "q = quit", (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
            # Mic level meter (right side): bar showing 0–100% of input level
            level = getattr(self._state, "_mic_level", 0.0)
            h, w = frame.shape[0], frame.shape[1]
            meter_w = 24
            meter_h = int(h * 0.5)
            margin_r = 14
            margin_t = int(h * 0.25)
            x1 = w - margin_r - meter_w
            x2 = w - margin_r
            y1 = margin_t
            y2 = margin_t + meter_h
            cv2.rectangle(frame, (x1, y1), (x2, y2), (50, 50, 50), 2)
            fill_h = int(meter_h * max(0, min(1, level)))
            if fill_h > 0:
                fy1 = y2 - fill_h
                cv2.rectangle(frame, (x1 + 1, fy1), (x2 - 1, y2 - 1), (0, 220, 0), -1)
            cv2.putText(frame, "Mic", (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
            cv2.imshow("himpublic (walk-around)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                self.request_stop()
            await asyncio.sleep(0.05)

    def _update_simulated_position(self, phase: str, obs: Observation | None) -> None:
        """Update simulated robot position on map based on phase (for command center map)."""
        step = 2.0
        if phase == Phase.SEARCH_LOCALIZE.value:
            # Drift along corridor (x oscillate)
            self._sim_map_x = (self._sim_map_x + step) % MAP_W
            self._sim_map_y = min(max(self._sim_map_y + 0.3, 130), 200)
        elif phase in (Phase.APPROACH_CONFIRM.value, Phase.ASSIST_COMMUNICATE.value, Phase.SCAN_CAPTURE.value, Phase.REPORT_SEND.value):
            # Move toward victim
            dx = VICTIM_MAP_X - self._sim_map_x
            dy = VICTIM_MAP_Y - self._sim_map_y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > step:
                self._sim_map_x += (dx / dist) * step
                self._sim_map_y += (dy / dist) * step
            self._sim_map_x = min(max(self._sim_map_x, 0), MAP_W)
            self._sim_map_y = min(max(self._sim_map_y, 0), MAP_H)
        else:
            # Small random drift
            self._sim_map_x = min(max(self._sim_map_x + (step * 0.3), 0), MAP_W)
            self._sim_map_y = min(max(self._sim_map_y, 0), MAP_H)

    async def _operator_message_loop(self) -> None:
        """Poll operator messages from command center; speak new ones via TTS and ack."""
        if self._cc_client is None or not self._cc_client._enabled or self._audio_io is None:
            return
        interval = 1.0
        while not self._stop_event.is_set():
            try:
                messages = self._cc_client.get_operator_messages()
                for i, msg in enumerate(messages):
                    if i > self._operator_messages_spoken_through_index:
                        text = (msg.get("text") or "").strip()
                        if text:
                            self._audio_io.speak(text)
                            if self._cc_client and self._cc_client._enabled:
                                self._cc_client.post_event({"event": "robot_said", "text": text})
                            self._operator_messages_spoken_through_index = i
                if messages and self._operator_messages_spoken_through_index >= 0:
                    self._cc_client.ack_operator_messages(self._operator_messages_spoken_through_index)
                    self._operator_messages_spoken_through_index = -1
            except Exception as e:
                logger.debug("Operator message poll failed: %s", e)
            await asyncio.sleep(interval)

    async def _telemetry_loop(self) -> None:
        """Post throttled telemetry at telemetry_hz; include simulated robot position; post latest frame for live feed."""
        if self._cc_client is None or not self.config.command_center_url:
            return
        interval = 1.0 / self.config.telemetry_hz if self.config.telemetry_hz > 0 else 1.0
        while not self._stop_event.is_set():
            obs = await self._state.get_observation()
            phase = await self._state.get_phase()
            debug_payload = await self._state.get_debug_payload()
            self._update_simulated_position(phase, obs)
            p_parsed = parse_phase(phase)
            status = PHASE_ANNOUNCE.get(p_parsed, phase)
            payload = {
                "event": EventType.HEARTBEAT.value,
                "timestamp": time.time(),
                "phase": phase,
                "phase_label": PHASE_LABELS.get(p_parsed, phase),
                "mode": phase,
                "status": status,
                "stage": phase,
                "boot_ready": self._state.boot_ready,
                "degraded_mode": self._state.degraded_mode,
                "num_persons": len(obs.persons) if obs else 0,
                "confidence": obs.confidence if obs else 0.0,
                "primary_person_center_offset": obs.primary_person_center_offset if obs else 0.0,
                "robot_map_x": round(self._sim_map_x, 1),
                "robot_map_y": round(self._sim_map_y, 1),
            }
            payload.update(debug_payload)
            self._cc_client.post_event(payload)
            # Post latest frame every tick so command center robot feed updates continuously
            if self._frame_store is not None:
                frame, _ = self._frame_store.get_latest()
                if frame is not None:
                    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    self._cc_client.post_snapshot(
                        jpeg.tobytes(),
                        "live.jpg",
                        {"event": "live_feed", "phase": phase},
                    )
            await asyncio.sleep(interval)

    async def run(self) -> None:
        """Run all tasks until stop requested. Then cancel tasks and cleanup."""
        logger.info("Agent starting (io=%s, video=%s). Ctrl+C to stop.", self.config.io_mode, self.config.video_mode)
        await self._boot_check()

        # Run SearchForPersonPhase as the first phase in SEARCH_LOCALIZE
        # This is a blocking call (in executor) before the main async loops start
        search_result = await self._run_search_phase()
        if search_result:
            logger.info("Search phase completed (found=%s), starting main loops", search_result.found)

        self._tasks = []
        _mic_thread = None
        if getattr(self.config, "show_preview", False) and getattr(self.config, "use_mic", True):
            _mic_thread = threading.Thread(
                target=_mic_level_thread,
                args=(self._state, self._stop_event),
                daemon=True,
            )
            _mic_thread.start()
        try:
            if self._video_source is not None:
                self._tasks.append(asyncio.create_task(self._perception_loop()))
                if getattr(self.config, "show_preview", False):
                    self._tasks.append(asyncio.create_task(self._preview_loop()))
            self._tasks.append(asyncio.create_task(self._audio_loop()))
            self._tasks.append(asyncio.create_task(self._policy_loop()))
            self._tasks.append(asyncio.create_task(self._actuation_loop()))
            if self._cc_client and self._cc_client._enabled:
                self._tasks.append(asyncio.create_task(self._telemetry_loop()))
                self._tasks.append(asyncio.create_task(self._operator_message_loop()))
            # Medical triage CV loop (additive — only runs if pipeline available)
            if self._medical_pipeline is not None:
                self._tasks.append(asyncio.create_task(self._medical_triage_loop()))
            await self._stop_event.wait()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        """Cancel tasks, release camera, stop robot. Save triage report if we have answers and none saved yet."""
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        # Save triage report on exit if we have answers (so Ctrl+C or early exit still produces a report)
        triage_answers = dict(getattr(self._state, "triage_answers", {}))
        if triage_answers and self._medical_pipeline is not None:
            report_path = getattr(self._medical_pipeline, "report_path", None) or getattr(
                self._medical_pipeline, "_report_path", None
            )
            if not report_path:
                try:
                    spoken = (
                        triage_answers.get("injury_location")
                        or triage_answers.get("injury_location_detail")
                        or triage_answers.get("bleeding_location")
                    )
                    if spoken:
                        self._medical_pipeline.set_spoken_body_region(str(spoken))
                    transcript_lines = list(getattr(self._state, "conversation_transcript", []))
                    path = self._medical_pipeline.build_report(
                        scene_summary="Automated triage assessment by rescue robot.",
                        victim_answers=triage_answers,
                        notes=[
                            "Generated on session end (shutdown).",
                            f"Transcript turns captured: {len(transcript_lines)}.",
                        ],
                        conversation_transcript=transcript_lines,
                        meta={"session_id": "shutdown"},
                    )
                    if path:
                        logger.info("Medical triage report saved on shutdown: %s", path)
                        try:
                            print(f"[Report saved] {Path(path).resolve()}", flush=True)
                        except Exception:
                            print(f"[Report saved] {path}", flush=True)
                except Exception as e:
                    logger.warning("Report build on shutdown failed: %s", e)
        if self._video_source is not None:
            self._video_source.release()
            self._video_source = None
        if self._robot is not None:
            self._robot.stop()
        if getattr(self.config, "show_preview", False):
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        logger.info("Agent stopped.")
