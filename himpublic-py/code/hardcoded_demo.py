#!/usr/bin/env python3
"""
Hardcoded Demo Sequence — full flow: locate by voice, navigate, debris, triage, scan, report.

Sequence:
  0. Locate by voice: "Is anyone there? Call out so I can find you." — listen for response
  1. Navigate to patient (walk, turn, walk, turn)
  2. Remove debris (crouch, keyframe, stand)
  3. Full triage Q&A (dialogue manager: MARCH questions, listen, structured answers → command center)
  4. Scan (head look-around, capture frames, post snapshots to command center)
  5. Build medical report (Markdown + PDF), post to command center
  6. Hold position

Command center gets: events (stage, robot_said, heard_response), comms, snapshots, final report.

SPEAK / LISTEN ON THE ROBOT (recommended for demo):
  Use --mode bridge with the robot bridge server running ON THE ROBOT (SSH).
  - speak() → POST /speak to bridge → robot plays TTS (espeak on robot).
  - listen() → POST /record to bridge → robot mic (arecord) → WAV to laptop → ASR → transcript.
  So the victim hears the robot and speaks to the robot; all audio I/O is on the robot.

Usage:
  # Robot speak/listen + motion via bridge (bridge must run on robot)
  python hardcoded_demo.py --mode bridge --bridge-url http://ROBOT_IP:9090 --command-center http://127.0.0.1:8000

  python hardcoded_demo.py --mode mock --command-center http://127.0.0.1:8000  # laptop only, type responses
  python hardcoded_demo.py --mode robot --network eth0  # SDK on robot; add --use-local-audio for laptop mic/speaker
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

# Ensure himpublic is importable (code/ is under himpublic-py)
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC = _PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("demo")

# ─── Tunable constants ────────────────────────────────────────────────
# Adjust these to match real-world results on your robot.

WALK_SPEED          = 0.5    # m/s forward velocity
TURN_SPEED          = 0.4    # rad/s rotation velocity (positive = left)
STEP_LENGTH         = 0.50   # meters per "step" (robot-dependent)
TURN_90_DURATION    = 3.9    # seconds to turn 90° at TURN_SPEED  (π/2 / 0.4 ≈ 3.93)
LISTEN_TIMEOUT      = 5.0    # max seconds to wait for initial "locate" response (stops sooner if you finish talking)
PAUSE_AFTER_SPEAK   = 0.8    # brief pause after speaking before listening
PAUSE_BETWEEN_QA    = 0.8    # pause between question-answer pairs
TRIAGE_LISTEN_S     = 6.0    # max seconds per triage question (shorter so we don't wait long after you're done)
# Scan / head look-around: ensure head settles and camera is stable before capture
HEAD_SETTLE_S       = 2.0    # seconds after head move before taking screenshot (reduces motion blur)
CAPTURE_INTERVAL_S  = 1.0    # seconds between captures (allow write + next pose)
SCAN_HEAD_POSES     = [      # (label, yaw_rad) for SDK; Bridge ignores yaw and just captures N frames
    ("left", 0.785),
    ("center", 0.0),
    ("right", -0.785),
    ("center2", 0.0),
]

# ─── Command center helper ────────────────────────────────────────────
def _cc_post_event(cc_client: Any, payload: dict[str, Any]) -> None:
    """Post event to command center if client is enabled."""
    if cc_client is None or not getattr(cc_client, "_enabled", False):
        return
    try:
        cc_client.post_event(payload)
    except Exception as e:
        logger.warning("Command center post_event failed: %s", e)

def _cc_post_snapshot(cc_client: Any, jpeg_path: Path, meta: dict | None = None) -> None:
    """Post a snapshot file to command center. Only posts if file exists and has size > 0."""
    if cc_client is None or not getattr(cc_client, "_enabled", False):
        return
    p = Path(jpeg_path)
    if not p.exists() or p.stat().st_size == 0:
        return
    try:
        data = p.read_bytes()
        cc_client.post_snapshot(data, p.name, meta=meta or {"phase": "scan"})
    except Exception as e:
        logger.warning("Command center post_snapshot failed: %s", e)


def _capture_and_save(
    robot: Any,
    filepath: Path,
    cc_client: Any,
    pose_label: str,
) -> bool:
    """
    Capture one frame, write to filepath, post to CC if saved. Returns True if file exists and has size > 0.
    """
    robot.capture_frame(str(filepath))
    time.sleep(0.3)  # allow filesystem flush
    if not filepath.exists() or filepath.stat().st_size == 0:
        logger.warning("Capture did not produce a valid file: %s", filepath)
        return False
    logger.info("Saved scan image: %s (%d bytes)", filepath.name, filepath.stat().st_size)
    _cc_post_snapshot(cc_client, filepath, meta={"phase": "scan", "pose": pose_label})
    return True

def _cc_post_report(cc_client: Any, payload: dict[str, Any]) -> bool:
    if cc_client is None or not getattr(cc_client, "_enabled", False):
        return False
    try:
        return cc_client.post_report(payload)
    except Exception as e:
        logger.warning("Command center post_report failed: %s", e)
        return False

# ─── Helper: timing for N steps ──────────────────────────────────────
def steps_to_seconds(n_steps: int) -> float:
    """Convert a step count to duration at WALK_SPEED."""
    distance = n_steps * STEP_LENGTH
    return distance / WALK_SPEED


# =====================================================================
#  ROBOT BACKENDS — swap between real SDK, bridge HTTP, or mock
# =====================================================================

class MockBackend:
    """Print-only backend for testing the sequence without a robot."""

    def speak(self, text: str) -> None:
        print(f"  🔊 ROBOT SAYS: \"{text}\"")

    def listen(self, timeout_s: float) -> Optional[str]:
        print(f"  🎤 LISTENING ({timeout_s:.0f}s) ...")
        try:
            # In mock mode, let the user type a response (or just press Enter to skip)
            import select
            if sys.platform != "win32":
                r, _, _ = select.select([sys.stdin], [], [], timeout_s)
                if r:
                    line = sys.stdin.readline().strip()
                    if line:
                        print(f"  👂 HEARD: \"{line}\"")
                        return line
            return None
        except Exception:
            return None

    def walk_forward(self, n_steps: int) -> None:
        dur = steps_to_seconds(n_steps)
        print(f"  🚶 WALK FORWARD {n_steps} steps ({dur:.1f}s at {WALK_SPEED} m/s)")
        time.sleep(0.5)  # short sim delay

    def turn_left(self) -> None:
        print(f"  ↰  TURN LEFT 90° ({TURN_90_DURATION:.1f}s at {TURN_SPEED} rad/s)")
        time.sleep(0.3)

    def turn_right(self) -> None:
        print(f"  ↱  TURN RIGHT 90° ({TURN_90_DURATION:.1f}s)")
        time.sleep(0.3)

    def crouch(self) -> None:
        print("  ⬇  CROUCH DOWN (switch to prepare/custom mode)")
        time.sleep(0.3)

    def stand(self) -> None:
        print("  ⬆  STAND UP (switch back to walking mode)")
        time.sleep(0.3)

    def play_keyframe(self, name: str) -> None:
        print(f"  🤖 PLAY KEYFRAME: \"{name}\"")
        time.sleep(0.5)

    def wave(self) -> None:
        print("  👋 WAVE HAND")
        time.sleep(0.3)

    def look_around(self) -> None:
        print("  👀 LOOK AROUND (rotate head left → center → right → center)")
        time.sleep(0.5)

    def head_move(self, yaw_rad: float) -> None:
        """Move head to yaw (radians). Mock: just log and wait settle time."""
        print(f"  👀 HEAD → yaw={yaw_rad:.2f} rad")
        time.sleep(HEAD_SETTLE_S)

    def capture_frame(self, filename: str) -> None:
        print(f"  📸 CAPTURE FRAME → {filename}")
        # Mock: create empty file so _capture_and_save sees a file (or small placeholder)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_bytes(b"\xff\xd8\xff")  # minimal JPEG magic bytes so file exists

    def stop(self) -> None:
        print("  🛑 STOP")


class SDKBackend:
    """Direct Booster SDK backend — runs on the robot or LAN."""

    def __init__(self, network_interface: str = ""):
        from booster_robotics_sdk_python import (
            B1LocoClient, ChannelFactory, RobotMode,
            B1LowCmdPublisher, B1LowStateSubscriber,
        )
        logger.info("Initializing Booster SDK (interface=%r) ...", network_interface)
        ChannelFactory.Instance().Init(domain_id=0, network_interface=network_interface)

        self.client = B1LocoClient()
        self.client.Init()

        # For keyframe playback
        self.cmd_pub = B1LowCmdPublisher()
        self.cmd_pub.InitChannel()
        self.low_state_msg = None
        self.state_sub = B1LowStateSubscriber(handler=self._on_low_state)
        self.state_sub.InitChannel()

        self.RobotMode = RobotMode
        self._audio = None  # set externally if needed
        logger.info("SDK connected.")

    def _on_low_state(self, msg):
        self.low_state_msg = msg

    def set_audio(self, audio_io):
        """Attach an AudioIO (LocalAudioIO or BridgeAudioIO) for speak/listen."""
        self._audio = audio_io

    # ── speech ────────────────────────────────────────────────────
    def speak(self, text: str) -> None:
        logger.info("SAY: %s", text)
        if self._audio:
            self._audio.speak(text)
        else:
            print(f"[TTS] {text}", flush=True)

    def listen(self, timeout_s: float) -> Optional[str]:
        if self._audio:
            return self._audio.listen(timeout_s)
        logger.warning("No audio backend — cannot listen")
        return None

    # ── locomotion (10Hz Move loop like walk_demo / walk_demo_v2) ───
    def _send_move(self, vx: float, vy: float, wz: float, duration_s: float) -> None:
        """Send Move at 10Hz for duration_s so the robot actually executes (single Move is one cycle)."""
        hz = 10
        steps = max(1, int(duration_s * hz))
        for _ in range(steps):
            self.client.Move(vx, vy, wz)
            time.sleep(1.0 / hz)
        self.client.Move(0.0, 0.0, 0.0)
        time.sleep(0.3)

    def walk_forward(self, n_steps: int) -> None:
        dur = steps_to_seconds(n_steps)
        logger.info("WALK FORWARD %d steps (%.1fs)", n_steps, dur)
        self.client.ChangeMode(self.RobotMode.kWalking)
        time.sleep(1)
        self._send_move(WALK_SPEED, 0.0, 0.0, dur)
        time.sleep(0.5)

    def turn_left(self) -> None:
        logger.info("TURN LEFT 90°")
        self.client.ChangeMode(self.RobotMode.kWalking)
        time.sleep(0.5)
        self._send_move(0.0, 0.0, TURN_SPEED, TURN_90_DURATION)
        time.sleep(0.5)

    def turn_right(self) -> None:
        logger.info("TURN RIGHT 90°")
        self.client.ChangeMode(self.RobotMode.kWalking)
        time.sleep(0.5)
        self._send_move(0.0, 0.0, -TURN_SPEED, TURN_90_DURATION)
        time.sleep(0.5)

    def crouch(self) -> None:
        """Switch to prepare mode (standing still, arms free)."""
        logger.info("CROUCH / PREPARE")
        self.client.Move(0.0, 0.0, 0.0)
        time.sleep(0.5)
        self.client.ChangeMode(self.RobotMode.kCustom)
        time.sleep(2)
        self.client.SwitchHandEndEffectorControlMode(True)
        time.sleep(1)

    def stand(self) -> None:
        """Switch back to walking-ready mode."""
        logger.info("STAND UP → walking mode")
        self.client.SwitchHandEndEffectorControlMode(False)
        time.sleep(1)
        self.client.ChangeMode(self.RobotMode.kPrepare)
        time.sleep(2)

    def play_keyframe(self, name: str) -> None:
        """Play a recorded keyframe motion by name."""
        from motion_capture import load_recording, JOINT_INDICES
        from booster_robotics_sdk_python import LowCmd, LowCmdType, MotorCmd

        logger.info("PLAY KEYFRAME: %s", name)
        recording = load_recording(name)
        if recording is None:
            logger.error("Keyframe '%s' not found! Skipping.", name)
            return

        kp, kd, weight = 20.0, 2.0, 1.0  # slow/safe
        for i, keyframe in enumerate(recording.keyframes):
            logger.info("  keyframe %d/%d", i + 1, len(recording.keyframes))
            motor_cmds = [MotorCmd() for _ in range(23)]
            for mc in motor_cmds:
                mc.mode = 0
                mc.q = 0.0
                mc.dq = 0.0
                mc.tau = 0.0
                mc.kp = 0.0
                mc.kd = 0.0
                mc.weight = 0.0
            for joint_name, q_val in keyframe["joints"].items():
                idx = JOINT_INDICES[joint_name]
                motor_cmds[idx].q = q_val
                motor_cmds[idx].kp = kp
                motor_cmds[idx].kd = kd
                motor_cmds[idx].weight = weight
            cmd = LowCmd()
            cmd.cmd_type = LowCmdType.SERIAL
            cmd.motor_cmd = motor_cmds
            self.cmd_pub.Write(cmd)
            time.sleep(0.5)

        logger.info("Keyframe '%s' done.", name)

    def wave(self) -> None:
        logger.info("WAVE")
        self.client.WaveHand()
        time.sleep(3)

    def look_around(self) -> None:
        """Full look-around sequence (left, center, right, center) with settle times."""
        logger.info("LOOK AROUND")
        for _label, yaw in SCAN_HEAD_POSES:
            self.head_move(yaw)

    def head_move(self, yaw_rad: float) -> None:
        """Move head to yaw (radians). Waits HEAD_SETTLE_S for camera to stabilize."""
        logger.info("HEAD → yaw=%.2f rad", yaw_rad)
        self.client.RotateHead(0.0, yaw_rad)
        time.sleep(HEAD_SETTLE_S)

    def capture_frame(self, filename: str) -> None:
        """Capture from robot camera. Requires camera subscriber in SDK; use bridge for actual JPEG."""
        logger.info("CAPTURE FRAME → %s (SDK mode: ensure camera feed is available)", filename)
        # If your SDK exposes get_frame elsewhere, wire it here; else use bridge for real capture
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_bytes(b"\xff\xd8\xff")  # placeholder so scan phase doesn't fail

    def stop(self) -> None:
        logger.info("STOP")
        self.client.Move(0.0, 0.0, 0.0)


class BridgeBackend:
    """Robot Bridge HTTP backend — sends commands from laptop over WiFi."""

    def __init__(self, bridge_url: str = "http://192.168.10.102:9090"):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from himpublic.io.robot_client import RobotBridgeClient, BridgeAudioIO

        self.client = RobotBridgeClient(bridge_url)
        self.audio = BridgeAudioIO(self.client)

        health = self.client.health()
        if health.get("status") == "unreachable":
            logger.error("Bridge unreachable at %s: %s", bridge_url, health)
            raise ConnectionError(f"Cannot reach bridge at {bridge_url}")
        logger.info("Bridge connected: %s", health)
        
        # Set robot to walking mode (like walk_demo.py / walk_demo_v2.py)
        logger.info("Initializing robot modes: PREP -> WALK")
        self.client.set_mode("prep")
        time.sleep(3)
        self.client.set_mode("walk")
        time.sleep(2)
        logger.info("Robot ready for motion")

    def speak(self, text: str) -> None:
        logger.info("SAY: %s", text)
        self.audio.speak(text)

    def listen(self, timeout_s: float) -> Optional[str]:
        return self.audio.listen(timeout_s)

    def _send_velocity_loop(self, vx: float, wz: float, duration_s: float) -> None:
        """Send velocity at 10Hz for duration_s so the bridge keeps applying Move (like walk_demo)."""
        hz = 10
        steps = max(1, int(duration_s * hz))
        for _ in range(steps):
            self.client.set_velocity(vx, wz)
            time.sleep(1.0 / hz)
        self.client.set_velocity(0.0, 0.0)
        time.sleep(0.3)

    def walk_forward(self, n_steps: int) -> None:
        dur = steps_to_seconds(n_steps)
        logger.info("WALK FORWARD %d steps (%.1fs)", n_steps, dur)
        self._send_velocity_loop(WALK_SPEED, 0.0, dur)
        time.sleep(0.5)

    def turn_left(self) -> None:
        logger.info("TURN LEFT 90°")
        self._send_velocity_loop(0.0, TURN_SPEED, TURN_90_DURATION)
        time.sleep(0.5)

    def turn_right(self) -> None:
        logger.info("TURN RIGHT 90°")
        self._send_velocity_loop(0.0, -TURN_SPEED, TURN_90_DURATION)
        time.sleep(0.5)

    def crouch(self) -> None:
        logger.info("CROUCH (bridge doesn't support mode switch — skipping)")

    def stand(self) -> None:
        logger.info("STAND (bridge doesn't support mode switch — skipping)")

    def play_keyframe(self, name: str) -> None:
        """Run keyframe via replay_capture.py when file exists (same as walk_demo_v2). Names: punch4, demo4, punch, remove_box."""
        code_dir = _SCRIPT_DIR
        # Resolve name to candidate files (punch4/demo4 -> punch4.json, punch.json; remove_box -> same + punch variants)
        candidates = []
        if name in ("punch4", "demo4", "punch"):
            candidates = ["punch4.json", "punch.json", "punch3.json", "punch2.json", "punch-v0.json"]
        elif name == "remove_box":
            candidates = ["remove_box.json", "punch4.json", "punch.json", "punch3.json", "punch2.json"]
        else:
            candidates = [f"{name}.json", "punch4.json", "punch.json"]
        punch_file = None
        for f in candidates:
            p = code_dir / f
            if p.exists():
                punch_file = p
                break
        replay_script = code_dir / "replay_capture.py"
        if not punch_file or not replay_script.exists():
            logger.warning("KEYFRAME '%s': no file in %s or replay_capture.py missing — skipping", name, code_dir)
            return
        logger.info("PLAY KEYFRAME via replay_capture: %s", punch_file.name)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(replay_script), str(punch_file), "--override-hold", "0.3", "--override-move", "0.15"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(code_dir),
            )
            for line in iter(proc.stdout.readline, b""):
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    logger.info("  replay: %s", text)
                if "Holding last keyframe" in text:
                    time.sleep(1)
                    proc.kill()
                    proc.wait()
                    logger.info("Keyframe '%s' done.", name)
                    return
            proc.wait()
        except Exception as e:
            logger.warning("replay_capture failed: %s", e)

    def wave(self) -> None:
        logger.info("WAVE")
        self.client.wave(hand="right", cycles=2)

    def look_around(self) -> None:
        """Per-pose capture; head_move uses bridge /head when available."""
        logger.info("LOOK AROUND")

    def head_move(self, yaw_rad: float) -> None:
        """Move head to yaw (radians). Uses bridge /head when available, else wait settle time."""
        if self.client.head(yaw_rad):
            logger.info("HEAD → yaw=%.2f rad", yaw_rad)
        else:
            logger.info("HEAD → yaw=%.2f (bridge: no head, waiting %.1fs)", yaw_rad, HEAD_SETTLE_S)
        time.sleep(HEAD_SETTLE_S)

    def capture_frame(self, filename: str) -> None:
        logger.info("CAPTURE FRAME → %s", filename)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        jpeg = self.client.get_frame_jpeg()
        if jpeg:
            Path(filename).write_bytes(jpeg)
            logger.info("  saved %d bytes", len(jpeg))
        else:
            logger.warning("  no frame available")

    def stop(self) -> None:
        self.client.stop()


# =====================================================================
#  THE HARDCODED SEQUENCE
# =====================================================================

def phase_banner(num: int, title: str) -> None:
    """Print a big visible phase header."""
    print("")
    print("=" * 60)
    print(f"  PHASE {num}: {title}")
    print("=" * 60)
    print("")


def ask_question(robot, question: str, cc_client: Any = None) -> Optional[str]:
    """Speak a question, pause, listen for response, return transcript. Optionally post to command center."""
    robot.speak(question)
    _cc_post_event(cc_client, {"event": "robot_said", "text": question, "stage": "triage"})
    time.sleep(PAUSE_AFTER_SPEAK)
    response = robot.listen(LISTEN_TIMEOUT)
    if response:
        logger.info("Patient said: %s", response)
        _cc_post_event(cc_client, {"event": "heard_response", "transcript": response, "stage": "triage"})
    else:
        logger.info("No response heard.")
    time.sleep(PAUSE_BETWEEN_QA)
    return response


def run_sequence(robot, cc_client: Any = None) -> None:
    """Execute the full hardcoded demo: locate by voice → navigate → debris → triage → scan → report → hold."""

    # Accumulated for report and command center
    location_hint: Optional[str] = None
    triage_answers: dict[str, Any] = {}
    conversation_transcript: list[str] = []
    scan_image_paths: list[str] = []
    incident_id = f"incident_{int(time.time())}"

    # ──────────────────────────────────────────────────────────────
    # PHASE 0: Locate by voice — wait for someone to speak
    # ──────────────────────────────────────────────────────────────
    phase_banner(0, "LOCATE BY VOICE")

    _cc_post_event(cc_client, {"event": "stage", "stage": "locate", "status": "Listening for victim."})
    robot.speak("Is anyone there? Call out so I can find you.")
    _cc_post_event(cc_client, {"event": "robot_said", "text": "Is anyone there? Call out so I can find you.", "stage": "locate"})
    time.sleep(PAUSE_AFTER_SPEAK)
    location_response = robot.listen(LISTEN_TIMEOUT)
    if location_response:
        location_hint = location_response.strip()
        logger.info("Victim responded (location hint): %s", location_hint)
        _cc_post_event(cc_client, {"event": "heard_response", "transcript": location_hint, "stage": "locate"})
        conversation_transcript.append(f"Robot: Is anyone there? Call out so I can find you.")
        conversation_transcript.append(f"Victim: {location_hint}")
    else:
        logger.info("No response; proceeding to navigate anyway.")
    time.sleep(0.5)

    robot.speak("I'm coming to you now. Please keep talking if you can so I can locate you.")
    _cc_post_event(cc_client, {"event": "robot_said", "text": "I'm coming to you now. Please keep talking if you can so I can locate you.", "stage": "locate"})
    time.sleep(1)

    # ──────────────────────────────────────────────────────────────
    # PHASE 1: Navigate to the patient
    # ──────────────────────────────────────────────────────────────
    phase_banner(1, "NAVIGATE TO PATIENT")

    _cc_post_event(cc_client, {"event": "stage", "stage": "navigate", "status": "Walking to victim."})
    logger.info("Walking forward 5 steps ...")
    robot.walk_forward(5)
    time.sleep(0.5)
    logger.info("Turning left 90° ...")
    robot.turn_left()
    time.sleep(0.5)
    logger.info("Walking forward 3 steps ...")
    robot.walk_forward(3)
    time.sleep(0.5)
    logger.info("Turning left 90° ...")
    robot.turn_left()
    time.sleep(0.5)
    robot.speak("I've reached you. Let me clear the debris.")
    _cc_post_event(cc_client, {"event": "robot_said", "text": "I've reached you. Let me clear the debris.", "stage": "navigate"})
    time.sleep(1)

    # ──────────────────────────────────────────────────────────────
    # PHASE 2: Remove debris (keyframe)
    # ──────────────────────────────────────────────────────────────
    phase_banner(2, "REMOVE DEBRIS")

    _cc_post_event(cc_client, {"event": "stage", "stage": "debris", "status": "Clearing debris."})
    robot.speak("I am going to remove the debris from on top of you. Please hold still.")
    _cc_post_event(cc_client, {"event": "robot_said", "text": "I am going to remove the debris from on top of you. Please hold still.", "stage": "debris"})
    time.sleep(1)
    robot.crouch()
    time.sleep(1)
    robot.play_keyframe("remove_box")
    time.sleep(1)
    robot.stand()
    time.sleep(1)
    robot.speak("I've cleared the debris from you.")
    _cc_post_event(cc_client, {"event": "robot_said", "text": "I've cleared the debris from you.", "stage": "debris"})
    time.sleep(1)

    # ──────────────────────────────────────────────────────────────
    # PHASE 3: Full triage Q&A (dialogue manager — rule-based)
    # ──────────────────────────────────────────────────────────────
    phase_banner(3, "TRIAGE Q&A (MARCH)")

    _cc_post_event(cc_client, {"event": "stage", "stage": "triage", "status": "Asking triage questions."})
    from himpublic.orchestrator.dialogue_manager import TriageDialogueManager

    dm = TriageDialogueManager()
    triage_complete = False
    turn_count = 0
    max_turns = 25  # safety cap

    while not triage_complete and turn_count < max_turns:
        turn_count += 1
        # First turn: no victim text (robot asks first question). Later: pass last response.
        victim_text: Optional[str] = None
        if turn_count > 1:
            victim_text = robot.listen(TRIAGE_LISTEN_S)
            if victim_text:
                victim_text = victim_text.strip()
                conversation_transcript.append(f"Victim: {victim_text}")
                _cc_post_event(cc_client, {"event": "heard_response", "transcript": victim_text, "stage": "triage"})

        result = dm.process_turn(
            victim_text=victim_text,
            current_question_key=dm.dialogue_state.last_question_key,
            now=time.monotonic(),
        )
        robot_utterance = result.get("robot_utterance") or "I'm here with you."
        triage_complete = result.get("triage_complete", False)
        triage_answers = result.get("triage_answers") or {}

        robot.speak(robot_utterance)
        _cc_post_event(cc_client, {"event": "robot_said", "text": robot_utterance, "stage": "triage"})
        conversation_transcript.append(f"Robot: {robot_utterance}")
        _cc_post_event(cc_client, {"event": "triage_update", "triage_answers": triage_answers, "timestamp": time.time()})
        time.sleep(PAUSE_AFTER_SPEAK)

    robot.speak("Thank you. I'm now going to scan the area to document your injuries for the medical team.")
    _cc_post_event(cc_client, {"event": "robot_said", "text": "Thank you. I'm now going to scan the area to document your injuries for the medical team.", "stage": "triage"})
    time.sleep(1.5)  # pause after triage before starting scan

    # ──────────────────────────────────────────────────────────────
    # PHASE 4: Head look-around and capture — one screenshot per head pose
    # ──────────────────────────────────────────────────────────────
    phase_banner(4, "SCAN: HEAD LOOK-AROUND AND CAPTURE (MEDICAL INJURIES)")

    _cc_post_event(cc_client, {"event": "stage", "stage": "scan", "status": "Looking around and capturing images for assessment."})
    output_dir = _SCRIPT_DIR.parent / "reports" / "scan_frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, (pose_label, yaw_rad) in enumerate(SCAN_HEAD_POSES):
        # Move head to pose and wait for camera to stabilize
        robot.head_move(yaw_rad)
        filepath = output_dir / f"scan_{incident_id}_{pose_label}_{i:02d}.jpg"
        if _capture_and_save(robot, filepath, cc_client, pose_label):
            scan_image_paths.append(str(filepath))
        time.sleep(CAPTURE_INTERVAL_S)

    # Only keep paths that exist and have content (for report and CC)
    scan_image_paths[:] = [p for p in scan_image_paths if Path(p).exists() and Path(p).stat().st_size > 0]
    logger.info("Scan complete: %d images saved and posted", len(scan_image_paths))
    time.sleep(0.5)  # brief pause before report phase

    # ──────────────────────────────────────────────────────────────
    # PHASE 5: Build medical report and post to command center
    # ──────────────────────────────────────────────────────────────
    phase_banner(5, "MEDICAL REPORT")

    _cc_post_event(cc_client, {"event": "stage", "stage": "report", "status": "Building report."})
    report_path: Optional[str] = None
    report_document = ""

    try:
        from himpublic.medical.triage_pipeline import TriagePipeline
        reports_dir = _SCRIPT_DIR.parent / "reports"
        pipeline = TriagePipeline(output_dir=str(reports_dir))
        if location_hint:
            pipeline.set_spoken_body_region(location_hint)
        # Speech-first: triage_answers and transcript drive the report; findings may be empty
        report_path = pipeline.build_report(
            scene_summary="Hardcoded demo: triage by voice, then scan. Automated assessment by rescue robot.",
            victim_answers=triage_answers,
            notes=["Generated from hardcoded demo. No CV findings; speech-first triage."],
            conversation_transcript=conversation_transcript,
            scene_images=scan_image_paths,
            meta={"incident_id": incident_id, "session_id": incident_id},
        )
        if report_path and Path(report_path).exists():
            report_document = Path(report_path).read_text(encoding="utf-8")
            logger.info("Medical report saved: %s", report_path)
    except Exception as e:
        logger.warning("Medical report build failed: %s — using fallback summary.", e)
        report_document = f"# Incident Report: {incident_id}\n\n## Patient summary (from triage)\n"
        for k, v in (triage_answers or {}).items():
            report_document += f"- **{k}:** {v}\n"
        report_document += "\n## Transcript\n" + "\n".join(conversation_transcript)

    report_payload = {
        "incident_id": incident_id,
        "run_id": incident_id,
        "timestamp": time.time(),
        "patient_summary": triage_answers,
        "patient_state": triage_answers,
        "location_hint": location_hint,
        "document": report_document,
        "transcript": conversation_transcript,
        "images": scan_image_paths,
        "report_path": report_path,
    }
    if _cc_post_report(cc_client, report_payload):
        logger.info("Report posted to command center.")
    else:
        logger.info("Report built locally (command center not configured or failed).")

    robot.speak(
        "I have completed my assessment and captured images for the medical team. "
        "Help is on the way. Please stay calm. I will stay here with you until help arrives."
    )
    _cc_post_event(cc_client, {"event": "robot_said", "text": "I have completed my assessment and captured images for the medical team. Help is on the way.", "stage": "report"})

    # ──────────────────────────────────────────────────────────────
    # PHASE 6: Hold position
    # ──────────────────────────────────────────────────────────────
    phase_banner(6, "HOLDING POSITION — SEQUENCE COMPLETE")

    _cc_post_event(cc_client, {"event": "stage", "stage": "done", "status": "Holding position with victim."})
    robot.stop()

    print("")
    print("-" * 40)
    print("  TRIAGE SUMMARY (for command center)")
    print("-" * 40)
    for key, val in (triage_answers or {}).items():
        label = str(key).replace("_", " ").title()
        print(f"  {label}: {val}")
    print("-" * 40)
    print("")

    robot.speak("I'm staying right here with you. Help is coming.")
    _cc_post_event(cc_client, {"event": "robot_said", "text": "I'm staying right here with you. Help is coming.", "stage": "done"})
    print("Demo complete. Command center has: events, comms, snapshots, report. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nShutting down.")
        robot.stop()


# =====================================================================
#  CLI
# =====================================================================

def parse_args():
    p = argparse.ArgumentParser(
        description="Hardcoded demo sequence — medical triage + navigation + keyframe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python hardcoded_demo.py --mode mock                 # dry run, no robot
  python hardcoded_demo.py --mode bridge               # via Robot Bridge HTTP
  python hardcoded_demo.py --mode robot --network eth0 # direct Booster SDK
        """,
    )
    p.add_argument(
        "--mode",
        choices=["mock", "robot", "bridge"],
        default="mock",
        help="Backend mode: mock (console only), robot (Booster SDK), bridge (HTTP)",
    )
    p.add_argument(
        "--network",
        type=str,
        default="",
        help="Network interface for Booster SDK (e.g. 'eth0', '127.0.0.1'). Only for --mode robot.",
    )
    p.add_argument(
        "--bridge-url",
        type=str,
        default="http://192.168.10.102:9090",
        help="Robot Bridge URL. Only for --mode bridge.",
    )
    p.add_argument(
        "--use-local-audio",
        action="store_true",
        help="When using --mode robot, use local mic+speaker (laptop) for TTS/ASR.",
    )
    p.add_argument(
        "--walk-speed", type=float, default=WALK_SPEED,
        help=f"Forward walk speed in m/s (default {WALK_SPEED})",
    )
    p.add_argument(
        "--step-length", type=float, default=STEP_LENGTH,
        help=f"Estimated step length in meters (default {STEP_LENGTH})",
    )
    p.add_argument(
        "--turn-duration", type=float, default=TURN_90_DURATION,
        help=f"Seconds to turn 90° (default {TURN_90_DURATION})",
    )
    p.add_argument(
        "--command-center",
        type=str,
        default=os.environ.get("HIMPUBLIC_COMMAND_CENTER_URL", "").strip(),
        help="Command center base URL (e.g. http://127.0.0.1:8000). Events, snapshots, and report are posted here.",
    )
    return p.parse_args()


def main():
    args = parse_args()

    # Allow overriding timing constants
    global WALK_SPEED, STEP_LENGTH, TURN_90_DURATION
    WALK_SPEED = args.walk_speed
    STEP_LENGTH = args.step_length
    TURN_90_DURATION = args.turn_duration

    print("")
    print("╔══════════════════════════════════════════════════════╗")
    print("║     HARDCODED DEMO SEQUENCE — MEDICAL RESCUE BOT    ║")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  Mode:        {args.mode:<39}║")
    print(f"║  Walk speed:  {WALK_SPEED} m/s{' ' * (34 - len(str(WALK_SPEED)))}║")
    print(f"║  Step length: {STEP_LENGTH} m{' ' * (36 - len(str(STEP_LENGTH)))}║")
    print(f"║  90° turn:    {TURN_90_DURATION} s{' ' * (36 - len(str(TURN_90_DURATION)))}║")
    print("╚══════════════════════════════════════════════════════╝")
    print("")

    if args.mode == "mock":
        robot = MockBackend()
    elif args.mode == "bridge":
        robot = BridgeBackend(bridge_url=args.bridge_url)
        logger.info("Bridge mode: speak/listen use ROBOT (TTS + mic via bridge at %s)", args.bridge_url)
    elif args.mode == "robot":
        robot = SDKBackend(network_interface=args.network)
        if args.use_local_audio:
            from himpublic.io.audio_io import LocalAudioIO
            robot.set_audio(LocalAudioIO(use_tts=True, use_mic=True))
    else:
        print(f"Unknown mode: {args.mode}")
        sys.exit(1)

    cc_client = None
    if args.command_center:
        try:
            from himpublic.comms.command_center_client import CommandCenterClient
            cc_client = CommandCenterClient(args.command_center.strip().rstrip("/"), timeout=5)
            logger.info("Command center: %s", args.command_center)
        except Exception as e:
            logger.warning("Command center client init failed: %s", e)

    try:
        run_sequence(robot, cc_client=cc_client)
    except KeyboardInterrupt:
        print("\nInterrupted! Stopping robot.")
        robot.stop()
    except Exception as e:
        logger.exception("Demo failed: %s", e)
        try:
            robot.stop()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
