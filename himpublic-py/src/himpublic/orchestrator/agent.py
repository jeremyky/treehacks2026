"""Always-on orchestrator: perception, audio, policy, actuation, telemetry. Clean shutdown on Ctrl+C."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import OrchestratorConfig
from .phases import Phase, PHASE_LABELS, PHASE_ANNOUNCE, parse_phase
from .events import EventManager, EventType
from .policy import Action, Decision, ReflexController, LLMPolicy
from .llm_adapter import propose_action
from himpublic.io.robot_interface import RobotInterface
from himpublic.io.mock_robot import MockRobot
from himpublic.io.video_source import BaseVideoSource, WebcamVideoSource, FileVideoSource, RobotVideoSource
from himpublic.io.audio_io import AudioIO, LocalAudioIO, RobotAudioIO
from himpublic.perception.person_detector import PersonDetector, draw_boxes
from himpublic.perception.types import Observation
from himpublic.perception.frame_store import LatestFrameStore, RingBuffer
from himpublic.comms.command_center_client import CommandCenterClient

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


def _apply_decision_params(
    state: SharedState,
    decision: Decision,
    now: float,
    cc_client: CommandCenterClient | None = None,
) -> None:
    """Apply decision.params to shared state: triage updates, capture_views, report send."""
    params = decision.params or {}
    if "clear_last_response" in params:
        state.last_response = None
    if "triage_step_index" in params:
        state.triage_step_index = int(params["triage_step_index"])
    if "triage_answers_delta" in params:
        delta = params["triage_answers_delta"]
        if isinstance(delta, dict):
            state.triage_answers.update(delta)
            if "consent_photos" in delta:
                v = delta["consent_photos"]
                state.consent_for_photos = bool(v) if isinstance(v, bool) else None
        _log_triage({"timestamp": now, "triage_answers": dict(state.triage_answers), "step_index": state.triage_step_index})
    if "last_prompt" in params:
        state.last_prompt = params["last_prompt"]
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
        _log_triage({"timestamp": now, "report_sent": state.report_sent, "report_payload": report_payload})


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


@dataclass
class SharedState:
    """State shared between agent tasks. Uses Phase for high-level mission phase."""
    observation: Observation | None = None
    decision: Decision | None = None
    phase: str = Phase.SEARCH_LOCALIZE.value  # current Phase.value
    phase_entered_at: float | None = None
    boot_ready: bool = False
    degraded_mode: bool = False  # e.g. no depth sensor
    last_response: str | None = None
    last_asked_at: float | None = None
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
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

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

        if config.io_mode == "robot":
            raise NotImplementedError("io=robot not yet implemented.")

        if config.io_mode == "local":
            self._video_source = _create_video_source(config)
            self._audio_io = _create_audio_io(config)
            self._person_detector = PersonDetector(
                model_path=config.yolo_model,
                threshold=config.detection_threshold,
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
        self._state.pending_phase_announcement = PHASE_ANNOUNCE.get(Phase.SEARCH_LOCALIZE, "Looking for person.")
        logger.info("Phase: %s – %s (ready=%s, degraded=%s)",
                    Phase.SEARCH_LOCALIZE.value, PHASE_LABELS.get(Phase.SEARCH_LOCALIZE, "Search"),
                    self._state.boot_ready, self._state.degraded_mode)

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
                    await loop.run_in_executor(
                        None,
                        lambda: self._event_manager.emit(
                            EventType.FOUND_PERSON,
                            {"num_persons": len(obs.persons), "confidence": obs.confidence},
                        ),
                    )
            await asyncio.sleep(0.02)

    async def _audio_loop(self) -> None:
        """When in WAIT_FOR_RESPONSE (decision.wait_for_response_s), listen and store transcript."""
        if self._audio_io is None:
            return
        while not self._stop_event.is_set():
            decision = await self._state.get_decision()
            wait_s = decision.wait_for_response_s if decision else None
            if wait_s is not None and wait_s > 0:
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: self._audio_io.listen(wait_s),
                )
                transcript = (raw or "").strip() or None
                if transcript:
                    self._state.last_response = transcript
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
                self._state.last_asked_at = time.monotonic()
                await self._state.set_decision(None)
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
            phase = conv.get("phase") or conv.get("mode") or Phase.SEARCH_LOCALIZE.value
            phase_entered_at = conv.get("phase_entered_at") or 0.0
            now = time.monotonic()

            llm_proposal = None
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
            await self._state.set_decision(decision)
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
        # Local: AudioIO for SAY/ASK, no robot motion. Post robot_said and robot_status to command center.
        last_spoke: str | None = None
        while not self._stop_event.is_set():
            # Speak pending phase announcement first (status out loud + post to active robot)
            pending = self._state.pending_phase_announcement
            if pending:
                self._state.pending_phase_announcement = None
                if self._audio_io:
                    self._audio_io.speak(pending)
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
            if decision and decision.say and decision.say != last_spoke:
                if self._audio_io:
                    self._audio_io.speak(decision.say)
                if self._cc_client and self._cc_client._enabled:
                    self._cc_client.post_event({"event": "robot_said", "text": decision.say})
                last_spoke = decision.say
                if decision.wait_for_response_s is not None:
                    self._state.last_asked_at = time.monotonic()
            if decision is None:
                last_spoke = None
            await asyncio.sleep(0.1)

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
        self._tasks = []
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
            await self._stop_event.wait()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        """Cancel tasks, release camera, stop robot."""
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
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
