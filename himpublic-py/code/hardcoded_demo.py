#!/usr/bin/env python3
"""
Hardcoded Demo Sequence — no CV, no LLM, just scripted steps.

Sequence:
  1. Ask initial medical triage questions, listen for responses
  2. Walk forward ~5 steps
  3. Turn left 90°
  4. Walk forward ~3 steps
  5. Turn left 90°
  6. Crouch down, run "remove_box" keyframe, stand back up
  7. Ask more medical questions, listen
  8. Scan images (capture frames from camera) and hold position

Usage:
  # With real robot (SDK + bridge for audio):
  python hardcoded_demo.py --mode robot --network-interface eth0

  # With bridge only (laptop → robot HTTP):
  python hardcoded_demo.py --mode bridge --bridge-url http://192.168.10.102:9090

  # Dry run / rehearsal (no robot, prints actions to console):
  python hardcoded_demo.py --mode mock
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
LISTEN_TIMEOUT      = 8.0    # seconds to wait for a spoken response
PAUSE_AFTER_SPEAK   = 1.0    # brief pause after speaking before listening
PAUSE_BETWEEN_QA    = 1.5    # pause between question-answer pairs

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

    def capture_frame(self, filename: str) -> None:
        print(f"  📸 CAPTURE FRAME → {filename}")

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

    # ── locomotion ────────────────────────────────────────────────
    def walk_forward(self, n_steps: int) -> None:
        dur = steps_to_seconds(n_steps)
        logger.info("WALK FORWARD %d steps (%.1fs)", n_steps, dur)
        self.client.ChangeMode(self.RobotMode.kWalking)
        time.sleep(1)
        self.client.Move(WALK_SPEED, 0.0, 0.0)
        time.sleep(dur)
        self.client.Move(0.0, 0.0, 0.0)
        time.sleep(0.5)

    def turn_left(self) -> None:
        logger.info("TURN LEFT 90°")
        self.client.ChangeMode(self.RobotMode.kWalking)
        time.sleep(0.5)
        self.client.Move(0.0, 0.0, TURN_SPEED)
        time.sleep(TURN_90_DURATION)
        self.client.Move(0.0, 0.0, 0.0)
        time.sleep(0.5)

    def turn_right(self) -> None:
        logger.info("TURN RIGHT 90°")
        self.client.ChangeMode(self.RobotMode.kWalking)
        time.sleep(0.5)
        self.client.Move(0.0, 0.0, -TURN_SPEED)
        time.sleep(TURN_90_DURATION)
        self.client.Move(0.0, 0.0, 0.0)
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
        logger.info("LOOK AROUND")
        self.client.RotateHead(0.0, 0.785)   # look left
        time.sleep(2)
        self.client.RotateHead(0.0, 0.0)     # center
        time.sleep(1)
        self.client.RotateHead(0.0, -0.785)  # look right
        time.sleep(2)
        self.client.RotateHead(0.0, 0.0)     # center
        time.sleep(1)

    def capture_frame(self, filename: str) -> None:
        """Placeholder — you'd grab from camera here."""
        logger.info("CAPTURE FRAME → %s (not implemented in SDK-only mode)", filename)

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

    def speak(self, text: str) -> None:
        logger.info("SAY: %s", text)
        self.audio.speak(text)

    def listen(self, timeout_s: float) -> Optional[str]:
        return self.audio.listen(timeout_s)

    def walk_forward(self, n_steps: int) -> None:
        dur = steps_to_seconds(n_steps)
        logger.info("WALK FORWARD %d steps (%.1fs)", n_steps, dur)
        self.client.set_velocity(WALK_SPEED, 0.0)
        time.sleep(dur)
        self.client.set_velocity(0.0, 0.0)
        time.sleep(0.5)

    def turn_left(self) -> None:
        logger.info("TURN LEFT 90°")
        self.client.set_velocity(0.0, TURN_SPEED)
        time.sleep(TURN_90_DURATION)
        self.client.set_velocity(0.0, 0.0)
        time.sleep(0.5)

    def turn_right(self) -> None:
        logger.info("TURN RIGHT 90°")
        self.client.set_velocity(0.0, -TURN_SPEED)
        time.sleep(TURN_90_DURATION)
        self.client.set_velocity(0.0, 0.0)
        time.sleep(0.5)

    def crouch(self) -> None:
        logger.info("CROUCH (bridge doesn't support mode switch — skipping)")

    def stand(self) -> None:
        logger.info("STAND (bridge doesn't support mode switch — skipping)")

    def play_keyframe(self, name: str) -> None:
        logger.warning("KEYFRAME '%s' requires SDK — skipping via bridge", name)

    def wave(self) -> None:
        logger.info("WAVE")
        self.client.wave(hand="right", cycles=2)

    def look_around(self) -> None:
        logger.info("LOOK AROUND (not available via bridge)")

    def capture_frame(self, filename: str) -> None:
        logger.info("CAPTURE FRAME → %s", filename)
        jpeg = self.client.get_frame_jpeg()
        if jpeg:
            with open(filename, "wb") as f:
                f.write(jpeg)
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


def ask_question(robot, question: str) -> Optional[str]:
    """Speak a question, pause, listen for response, return transcript."""
    robot.speak(question)
    time.sleep(PAUSE_AFTER_SPEAK)
    response = robot.listen(LISTEN_TIMEOUT)
    if response:
        logger.info("Patient said: %s", response)
    else:
        logger.info("No response heard.")
    time.sleep(PAUSE_BETWEEN_QA)
    return response


def run_sequence(robot) -> None:
    """Execute the full hardcoded demo sequence."""

    responses = {}  # store patient answers for later

    # ──────────────────────────────────────────────────────────────
    # PHASE 1: Initial Medical Triage Questions
    # ──────────────────────────────────────────────────────────────
    phase_banner(1, "INITIAL MEDICAL TRIAGE")

    robot.wave()

    robot.speak(
        "Hello, I am a medical rescue robot. I have been deployed to assist you. "
        "I'm going to ask you a few questions to assess your condition."
    )
    time.sleep(1)

    responses["name"] = ask_question(
        robot, "Can you tell me your name?"
    )
    responses["location_of_pain"] = ask_question(
        robot, "Can you tell me where you are injured or feeling pain?"
    )
    responses["pain_level"] = ask_question(
        robot, "On a scale of 1 to 10, how much pain are you in?"
    )
    responses["consciousness"] = ask_question(
        robot, "Do you know what day it is and where you are?"
    )
    responses["allergies"] = ask_question(
        robot, "Do you have any known allergies or medical conditions?"
    )

    robot.speak("Thank you. I'm going to come closer to you now. Please stay still.")
    time.sleep(1)

    # ──────────────────────────────────────────────────────────────
    # PHASE 2: Navigate to the Patient
    # ──────────────────────────────────────────────────────────────
    phase_banner(2, "NAVIGATE TO PATIENT")

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
    time.sleep(1)

    # ──────────────────────────────────────────────────────────────
    # PHASE 3: Remove the Box (Keyframe)
    # ──────────────────────────────────────────────────────────────
    phase_banner(3, "REMOVE DEBRIS (KEYFRAME)")

    robot.speak("I am going to remove the debris from on top of you. Please hold still.")
    time.sleep(1)

    # Crouch / go into custom mode for arm control
    robot.crouch()
    time.sleep(1)

    # Play the keyframe (you need to have recorded this beforehand
    # using: python motion_capture.py record remove_box)
    robot.play_keyframe("remove_box")
    time.sleep(1)

    # Stand back up
    robot.stand()
    time.sleep(1)

    robot.speak("I've cleared the debris from you.")
    time.sleep(1)

    # ──────────────────────────────────────────────────────────────
    # PHASE 4: Follow-up Medical Questions
    # ──────────────────────────────────────────────────────────────
    phase_banner(4, "FOLLOW-UP MEDICAL ASSESSMENT")

    robot.speak("Now that the debris is cleared, I need to ask a few more questions.")
    time.sleep(0.5)

    responses["feel_legs"] = ask_question(
        robot, "Can you feel your legs? Try to wiggle your toes."
    )
    responses["breathing"] = ask_question(
        robot, "Are you having any difficulty breathing?"
    )
    responses["bleeding"] = ask_question(
        robot, "Can you see any active bleeding on your body?"
    )
    responses["head_injury"] = ask_question(
        robot, "Did you hit your head? Are you feeling dizzy or nauseous?"
    )
    responses["mobility"] = ask_question(
        robot, "Do you think you can move, or does anything feel broken?"
    )

    robot.speak(
        "Thank you for your answers. I'm now going to scan the area to document "
        "your injuries for the medical team."
    )
    time.sleep(1)

    # ──────────────────────────────────────────────────────────────
    # PHASE 5: Scan / Capture Images and Hold
    # ──────────────────────────────────────────────────────────────
    phase_banner(5, "SCAN AND HOLD POSITION")

    # Look around to capture from different angles
    robot.look_around()

    # Capture a few frames
    output_dir = Path(__file__).parent.parent / "assets" / "scan_frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    for i in range(3):
        filename = str(output_dir / f"scan_{i:02d}.jpg")
        robot.capture_frame(filename)
        time.sleep(1)

    robot.speak(
        "I have completed my assessment and captured images for the medical team. "
        "Help is on the way. Please stay calm and try not to move. "
        "I will stay here with you until help arrives."
    )

    # ──────────────────────────────────────────────────────────────
    # DONE — Hold position
    # ──────────────────────────────────────────────────────────────
    phase_banner(6, "HOLDING POSITION — SEQUENCE COMPLETE")

    robot.stop()

    # Print summary of responses
    print("")
    print("-" * 40)
    print("  PATIENT RESPONSE SUMMARY")
    print("-" * 40)
    for key, val in responses.items():
        label = key.replace("_", " ").title()
        print(f"  {label}: {val or '(no response)'}")
    print("-" * 40)
    print("")

    # Stay alive so the robot holds position
    robot.speak("I'm staying right here with you. Help is coming.")
    print("Demo complete. Press Ctrl+C to exit.")
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
    elif args.mode == "robot":
        robot = SDKBackend(network_interface=args.network)
        if args.use_local_audio:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
            from himpublic.io.audio_io import LocalAudioIO
            robot.set_audio(LocalAudioIO(use_tts=True, use_mic=True))
    else:
        print(f"Unknown mode: {args.mode}")
        sys.exit(1)

    try:
        run_sequence(robot)
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
