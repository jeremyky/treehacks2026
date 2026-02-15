#!/usr/bin/env python3
"""
Walk Demo V4 — Voice + Walking + demo4 + Head keyframe + Smart LLM Triage + Command Center.

Flow:
  1. "Is anyone there?" → listen → "I'm coming!"
  2. Walk: forward 5, left, forward 3, left (UNCHANGED - works)
  3. Remove debris (demo4 keyframe)
  4. Smart LLM-powered medical triage with dialogue manager
  5. Head keyframe (scan/documentation)
  6. Full medical report generation
  7. All speech + transcripts streamed to command center webapp

Usage (on robot):
    cd ~/Workspace/himpublic/code
    export OPENAI_API_KEY='sk-...'
    python3 walk_demo_v4.py --cc http://YOUR_LAPTOP_IP:8000
    python3 walk_demo_v4.py --cc http://YOUR_LAPTOP_IP:8000 --no-walk
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests as http_requests

from booster_robotics_sdk_python import (
    B1LocoClient,
    ChannelFactory,
    RobotMode,
)

# Add himpublic to path for medical/dialogue imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_HIMPUBLIC_SRC = _SCRIPT_DIR.parent / "src"
if str(_HIMPUBLIC_SRC) not in sys.path:
    sys.path.insert(0, str(_HIMPUBLIC_SRC))

# ── Audio hardware ───────────────────────────────────────────────
ALSA_CAPTURE_DEVICE = "hw:1,0"
CAPTURE_RATE = 16000
CAPTURE_CHANNELS = 1

# ── Walk tunables ────────────────────────────────────────────────
CFG = {
    "walk_speed": 0.5,
    "turn_speed": 0.4,
    "step_length": 0.50,
    "turn_90_time": 3.9,
}

# ── Command center URL (set via --cc flag) ───────────────────────
CC_URL = None  # e.g. "http://192.168.x.x:8000"

# ── Triage data store ────────────────────────────────────────────
conversation_transcript = []  # Full robot + victim transcript for report
triage_answers = {}  # Structured answers collected by dialogue manager


# =====================================================================
#  Command Center — post events so the webapp shows everything live
# =====================================================================
def cc_post_event(payload: dict):
    """POST to command center /event. Silently fails if CC not set."""
    if not CC_URL:
        return
    try:
        resp = http_requests.post(f"{CC_URL}/event", json=payload, timeout=3)
        if resp.status_code != 200:
            print(f"  [CC event warning: {resp.status_code}]")
    except Exception as e:
        # First error: log it
        if not hasattr(cc_post_event, '_warned'):
            print(f"  [CC event error: {e}]")
            cc_post_event._warned = True


def cc_robot_said(text: str, stage: str = ""):
    """Tell command center the robot said something."""
    payload = {"event": "robot_said", "text": text, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    cc_post_event(payload)
    print(f"  → CC: robot said")


def cc_heard(transcript: str):
    """Tell command center what was heard."""
    if transcript:
        payload = {
            "event": "heard_response",
            "transcript": transcript,
            "timestamp": time.time(),
        }
        cc_post_event(payload)
        print(f"  → CC: heard '{transcript[:50]}...'")
    else:
        print(f"  → CC: (no transcript to send)")


def cc_status(status: str, stage: str = ""):
    """Post a status/stage update."""
    payload = {"event": "heartbeat", "status": status, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    cc_post_event(payload)


def cc_post_snapshot(jpeg_bytes: bytes, meta: dict = None):
    """POST a camera frame to command center."""
    if not CC_URL or not jpeg_bytes:
        return
    try:
        files = {"file": ("snapshot.jpg", jpeg_bytes, "image/jpeg")}
        data = {}
        if meta:
            data["metadata"] = json.dumps(meta)
        resp = http_requests.post(f"{CC_URL}/snapshot", files=files, data=data, timeout=5)
        if resp.status_code == 200 and not hasattr(cc_post_snapshot, '_first_ok'):
            print(f"[Camera] ✓ First frame posted to command center ({len(jpeg_bytes)} bytes)")
            cc_post_snapshot._first_ok = True
    except Exception as e:
        if not hasattr(cc_post_snapshot, '_warned'):
            print(f"[Camera] Snapshot post error: {e}")
            cc_post_snapshot._warned = True


# =====================================================================
#  Background camera feed → command center (pulls from bridge /frame)
# =====================================================================
_camera_thread = None
_camera_stop = False
_bridge_url = None  # Set by main() when robot is initialized


def camera_capture_loop():
    """
    Pull frames from robot bridge at http://127.0.0.1:9090/frame and post to command center.
    This works because both bridge and demo run ON the robot.
    """
    global _camera_stop, _bridge_url
    
    if not _bridge_url:
        print("[Camera] No bridge URL set - skipping camera feed")
        return
    
    # Use local bridge since we're running ON the robot
    local_bridge = "http://127.0.0.1:9090"
    
    print(f"[Camera] Starting feed from {local_bridge}/frame")
    consecutive_failures = 0
    
    try:
        while not _camera_stop:
            try:
                # GET frame from bridge (JPEG bytes)
                resp = http_requests.get(f"{local_bridge}/frame?quality=70", timeout=2)
                if resp.status_code == 200 and resp.content:
                    cc_post_snapshot(resp.content, meta={"source": "robot_camera", "via": "bridge"})
                    consecutive_failures = 0
                elif resp.status_code == 503:
                    # Camera unavailable (ROS not sourced or perception stopped)
                    consecutive_failures += 1
                    if consecutive_failures == 1:
                        print("[Camera] Bridge says camera unavailable (did you source ROS?)")
                    if consecutive_failures > 10:
                        print("[Camera] Too many failures, stopping feed")
                        break
                else:
                    consecutive_failures += 1
            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures == 1:
                    print(f"[Camera] Error getting frame: {e}")
                if consecutive_failures > 10:
                    print("[Camera] Too many errors, stopping feed")
                    break
            
            time.sleep(0.3)  # post every 0.3s for faster camera updates
        
        print("[Camera] Feed stopped")
    except Exception as e:
        print(f"[Camera] Fatal error: {e}")


def start_camera_feed(bridge_url: str = None):
    """Start camera feed thread. Pass bridge_url to enable."""
    global _camera_thread, _camera_stop, _bridge_url
    _bridge_url = bridge_url
    _camera_stop = False
    _camera_thread = threading.Thread(target=camera_capture_loop, daemon=True)
    _camera_thread.start()


def stop_camera_feed():
    global _camera_stop
    _camera_stop = True


# =====================================================================
#  TTS (espeak on robot)
# =====================================================================
def speak(text: str, stage: str = ""):
    """
    Speak via espeak and log to command center.
    
    Note: User CAN start talking while robot is speaking. The next listen()
    call will capture it (recording starts immediately after robot finishes,
    then waits 2s for victim to start/continue speaking).
    """
    print(f"🔊 ROBOT: {text}")
    cc_robot_said(text, stage=stage)
    try:
        subprocess.run(["espeak", text], timeout=10, check=False)
    except Exception as e:
        print(f"  [TTS error: {e}]")
    # No extra pause here - listen_with_retry() handles the 2s wait


# =====================================================================
#  Record + Transcribe (with smart timing)
# =====================================================================
def record_audio(duration_s: float = 2.0) -> bytes:
    """Record audio from robot mic for up to duration_s."""
    print(f"🎤 LISTENING (up to {duration_s:.0f}s)...")
    try:
        proc = subprocess.run(
            [
                "arecord", "-D", ALSA_CAPTURE_DEVICE,
                "-f", "S16_LE", "-r", str(CAPTURE_RATE),
                "-c", str(CAPTURE_CHANNELS),
                "-d", str(int(duration_s + 0.5)),
                "-t", "wav", "-q", "-",
            ],
            capture_output=True, timeout=duration_s + 10,
        )
        if proc.returncode != 0:
            return b""
        return proc.stdout
    except Exception as e:
        print(f"  [record error: {e}]")
        return b""


def transcribe(wav_bytes: bytes) -> str:
    """Transcribe audio using local Whisper on GPU (faster-whisper) or fallback to OpenAI cloud."""
    if not wav_bytes:
        return ""
    
    # Try local GPU Whisper first (FAST)
    try:
        from faster_whisper import WhisperModel
        
        # Initialize model lazily (cached globally)
        if not hasattr(transcribe, '_local_model'):
            print("  [Loading Whisper on GPU... (one-time)]")
            # Use GPU with int8 quantization for speed
            transcribe._local_model = WhisperModel(
                "base",  # or "small" for better accuracy
                device="cuda",
                compute_type="int8",
            )
            print("  [✓ Whisper loaded on GPU]")
        
        # Save WAV to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp = f.name
        
        try:
            segments, info = transcribe._local_model.transcribe(tmp, language="en", beam_size=1)
            text = " ".join([seg.text for seg in segments]).strip()
            if text:
                print(f"👂 HEARD (GPU): {text}")
            return text
        finally:
            os.unlink(tmp)
            
    except ImportError:
        print("  [faster-whisper not installed - falling back to OpenAI cloud]")
        print("  [Install on robot: pip3 install faster-whisper]")
        # Fall through to cloud API
    except Exception as e:
        print(f"  [GPU Whisper error: {e} - falling back to cloud]")
        # Fall through to cloud API
    
    # Fallback: OpenAI cloud API (SLOW but reliable)
    try:
        from openai import OpenAI
        client = OpenAI()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp = f.name
        try:
            with open(tmp, "rb") as af:
                result = client.audio.transcriptions.create(
                    model="whisper-1", file=af, language="en",
                )
            text = result.text.strip()
            if text:
                print(f"👂 HEARD (cloud): {text}")
            return text
        finally:
            os.unlink(tmp)
    except Exception as e:
        print(f"  [transcribe error: {e}]")
        return ""


def listen_with_retry(max_duration_s: float = 3.0, retries: int = 1) -> str:
    """
    Listen for victim response with smart timing and retry logic.
    
    - Waits 0.5s after robot stops talking (quick response time)
    - Records for up to max_duration_s (stops sooner if you finish talking)
    - If no response, retries up to `retries` times
    - After max retries, returns None (don't get stuck)
    
    Returns:
        Transcribed text or None if no response after retries
    """
    # Quick wait after robot speech for victim to start talking
    time.sleep(0.5)  # reduced from 2s
    
    for attempt in range(retries + 1):
        if attempt > 0:
            print(f"  (retry {attempt}/{retries})...")
            time.sleep(0.3)  # reduced from 1s
        
        wav = record_audio(max_duration_s)
        text = transcribe(wav)
        
        if text:
            cc_heard(text)  # Post to command center
            return text
    
    # No response after retries
    print("  (no response heard after retries)")
    return None


def listen(duration_s: float = 3.0) -> str:
    """Simple listen wrapper (single attempt, for backward compat)."""
    time.sleep(0.5)  # quick wait after robot speech
    wav = record_audio(duration_s)
    text = transcribe(wav)
    cc_heard(text)
    return text or ""


# =====================================================================
#  Hardcoded transcript (FAST - no mic, no LLM, no waiting)
# =====================================================================
HARDCODED_SCRIPT = [
    ("Robot", "Can you tell me your name?"),
    ("Victim", "Sarah Martinez"),
    ("Robot", "Thank you Sarah. Where are you hurt?"),
    ("Victim", "My left leg and my chest"),
    ("Robot", "I've noted that. On a scale of 1 to 10, how severe is the pain?"),
    ("Victim", "It's about an 8"),
    ("Robot", "That's very serious pain. I understand. Are you having any trouble breathing?"),
    ("Victim", "A little, it hurts when I breathe"),
    ("Robot", "Noted. Can you move your legs at all?"),
    ("Victim", "No, I can't move my left leg"),
    ("Robot", "Understood. Are you bleeding anywhere?"),
    ("Victim", "Yes, from my leg"),
    ("Robot", "Okay, I've documented everything. Help is on the way. The medical team will be here soon."),
]

def run_hardcoded_triage():
    """Fast pre-scripted triage (no mic, no LLM, no delays)."""
    global triage_answers, conversation_transcript
    
    print("\n" + "=" * 50)
    print("  HARDCODED TRIAGE (FAST MODE)")
    print("=" * 50)
    
    triage_answers = {
        "name": "Sarah Martinez",
        "injury_location": "left leg and chest",
        "pain_level": "8",
        "breathing": "difficulty",
        "can_move_legs": "no (left leg)",
        "bleeding": "yes (leg)",
    }
    
    for role, text in HARDCODED_SCRIPT:
        if role == "Robot":
            speak(text, stage="TRIAGE")
            time.sleep(0.3)  # minimal pause (just for TTS to finish)
        else:
            print(f"  [Simulated victim: {text}]")
            cc_heard(text)
            time.sleep(0.1)  # instant response
        conversation_transcript.append(f"{role}: {text}")
    
    print("=" * 50)
    print("  Triage complete (hardcoded)")
    print("=" * 50)
    
    return triage_answers


# =====================================================================
#  Smart LLM-powered triage dialogue (with retry logic)
# =====================================================================
def run_triage_dialogue():
    """
    Run full triage conversation using TriageDialogueManager (LLM-powered).
    
    Smart timing:
    - Robot waits 2s after speaking for victim to start
    - Records for up to 6s (captures full responses)
    - If no response after 2 retries, continues anyway (doesn't get stuck)
    - Victim can interrupt/talk while robot is speaking
    """
    from himpublic.orchestrator.dialogue_manager import TriageDialogueManager
    
    global triage_answers, conversation_transcript
    
    dm = TriageDialogueManager()
    triage_complete = False
    turn_count = 0
    max_turns = 25  # safety cap
    no_response_count = 0  # track consecutive no-responses
    
    print("\n" + "=" * 50)
    print("  SMART LLM TRIAGE (Dialogue Manager)")
    print("=" * 50)
    
    while not triage_complete and turn_count < max_turns:
        turn_count += 1
        
        # First turn: robot asks first question (no victim text yet)
        victim_text = None
        if turn_count > 1:
            # Smart listen with retry (1 attempt, 3s max - faster responses)
            victim_text = listen_with_retry(max_duration_s=3.0, retries=1)
            
            if victim_text:
                victim_text = victim_text.strip()
                conversation_transcript.append(f"Victim: {victim_text}")
                no_response_count = 0  # reset counter
            else:
                no_response_count += 1
                print(f"  [No response detected (count: {no_response_count})]")
                
                # After 2 consecutive no-responses, assume victim can't talk (faster)
                if no_response_count >= 2:
                    print("  [Victim appears unable to respond - proceeding with visual assessment only]")
                    speak("I understand you may not be able to talk. I'll document what I can see and get help to you.", "TRIAGE")
                    conversation_transcript.append("Robot: I understand you may not be able to talk. I'll document what I can see and get help to you.")
                    break
        
        # Process turn through dialogue manager
        result = dm.process_turn(
            victim_text=victim_text,
            current_question_key=dm.dialogue_state.last_question_key,
            now=time.monotonic(),
        )
        
        robot_utterance = result.get("robot_utterance") or "I'm here with you."
        triage_complete = result.get("triage_complete", False)
        triage_answers = result.get("triage_answers") or {}
        
        # Robot speaks (victim can interrupt - next listen will catch it)
        speak(robot_utterance, stage="TRIAGE")
        conversation_transcript.append(f"Robot: {robot_utterance}")
        
        # Post update to command center
        if CC_URL:
            try:
                http_requests.post(
                    f"{CC_URL}/event",
                    json={"event": "triage_update", "triage_answers": triage_answers, "timestamp": time.time()},
                    timeout=3,
                )
            except Exception:
                pass
    
    print("=" * 50)
    print(f"  Triage complete after {turn_count} turns")
    print("=" * 50)
    
    return triage_answers


# =====================================================================
#  Walking
# =====================================================================
def send_move(client, vx, vy, vz, duration, label=""):
    if label:
        print(f"\n>> {label}")
    hz = 10
    for _ in range(int(duration * hz)):
        client.Move(vx, vy, vz)
        time.sleep(1.0 / hz)
    client.Move(0.0, 0.0, 0.0)
    time.sleep(0.3)


def walk_forward(client, n_steps):
    dur = (n_steps * CFG["step_length"]) / CFG["walk_speed"]
    send_move(client, CFG["walk_speed"], 0.0, 0.0, dur,
              f"WALK FORWARD {n_steps} steps ({dur:.1f}s)")


def turn_left(client):
    send_move(client, 0.0, 0.0, CFG["turn_speed"], CFG["turn_90_time"],
              f"TURN LEFT 90° ({CFG['turn_90_time']:.1f}s)")


def stop(client):
    print(">> STOP")
    client.Move(0.0, 0.0, 0.0)


# =====================================================================
#  Keyframe player helper
# =====================================================================
def play_keyframe(keyframe_name: str, code_dir: str) -> bool:
    """Play a keyframe JSON file via replay_capture.py. Returns True if played successfully."""
    # Look for keyframe file
    candidates = [f"{keyframe_name}.json"]
    # Add common alternates if the name is generic
    if keyframe_name in ["demo", "demo4"]:
        candidates.extend(["demo4.json", "demo.json"])
    if keyframe_name == "head":
        candidates.extend(["head.json", "head_scan.json", "look_around.json"])
    
    keyframe_file = None
    for name in candidates:
        p = os.path.join(code_dir, name)
        if os.path.exists(p):
            keyframe_file = p
            break
    
    if not keyframe_file:
        print(f"   ⚠ No keyframe file found for '{keyframe_name}' — skipping")
        return False
    
    print(f"\n>> PLAYING KEYFRAME: {os.path.basename(keyframe_file)}")
    
    # replay_capture.py holds forever after last keyframe — we watch
    # stdout for "Holding last keyframe" then kill it
    try:
        proc = subprocess.Popen(
            [
                sys.executable, "-u",  # unbuffered output
                os.path.join(code_dir, "replay_capture.py"),
                keyframe_file,
                "--override-hold", "0.3",
                "--override-move", "0.15",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        # Read output line by line until we see the hold message
        while True:
            line = proc.stdout.readline()
            if not line:
                break  # process ended
            text = line.decode(errors="replace").strip()
            if text:
                print(f"   {text}")
            if "Holding last keyframe" in text:
                # All keyframes done — give it a moment then kill
                time.sleep(1)
                proc.kill()
                proc.wait()
                print(f"   ✓ Keyframe '{keyframe_name}' complete!")
                return True
        # Process ended on its own
        proc.wait()
        print(f"   replay_capture.py exited with code {proc.returncode}")
        return proc.returncode == 0
    except Exception as e:
        print(f"   ⚠ Keyframe playback error: {e}")
        return False


# =====================================================================
#  Main
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="Walk demo v4 (demo4 + head keyframes)")
    parser.add_argument("--network", default="")
    parser.add_argument("--cc", type=str, default="",
                        help="Command center URL, e.g. http://192.168.1.5:8000")
    parser.add_argument("--no-walk", action="store_true")
    parser.add_argument("--no-voice", action="store_true")
    parser.add_argument("--start-triage", action="store_true",
                        help="Skip walking and debris, start at triage (for practice)")
    parser.add_argument("--hardcode-transcript", action="store_true",
                        help="Use pre-scripted conversation (FAST, no mic/transcription/LLM delays)")
    parser.add_argument("--walk-speed", type=float, default=0.5)
    parser.add_argument("--turn-time", type=float, default=3.9)
    parser.add_argument("--step-length", type=float, default=0.50)
    args = parser.parse_args()

    CFG["walk_speed"] = args.walk_speed
    CFG["turn_90_time"] = args.turn_time
    CFG["step_length"] = args.step_length

    global CC_URL
    CC_URL = args.cc.rstrip("/") if args.cc else None

    do_walk = not args.no_walk
    do_voice = not args.no_voice
    
    global conversation_transcript, triage_answers
    conversation_transcript = []
    triage_answers = {}

    print("=" * 50)
    print("  WALK DEMO V4 — Smart LLM + demo4 + head")
    print(f"  Command Center: {CC_URL or 'OFF'}")
    print("=" * 50)

    # Connect
    print("Connecting to robot SDK...")
    ChannelFactory.Instance().Init(domain_id=0, network_interface=args.network)
    client = B1LocoClient()
    client.Init()
    print("Connected to SDK!\n")

    # Verify bridge is running (for camera feed)
    bridge_ok = False
    try:
        resp = http_requests.get("http://127.0.0.1:9090/health", timeout=2)
        if resp.status_code == 200:
            health = resp.json()
            bridge_ok = health.get("camera_ok", False)
            print(f"Bridge: ✓ Connected (camera: {'✓' if bridge_ok else '✗'})")
            if not bridge_ok:
                print("  ⚠ Bridge camera unavailable - did you source ROS before starting bridge?")
                print("    Run: source /opt/ros/humble/setup.bash && python3 ~/server.py --allow-motion")
        else:
            print("⚠ Bridge not responding at 127.0.0.1:9090")
    except Exception as e:
        print(f"⚠ Bridge connection failed: {e}")
        print("  Camera feed will not work. Make sure bridge is running:")
        print("    python3 ~/server.py --allow-motion")
    
    # Verify command center connectivity (so events/transcripts/camera reach webapp)
    if CC_URL:
        try:
            resp = http_requests.get(f"{CC_URL}/latest", timeout=2)
            if resp.status_code == 200:
                print(f"Command Center: ✓ Connected at {CC_URL}")
                print("  → Robot speech, transcripts, and camera will stream to webapp")
            else:
                print(f"⚠ Command Center responded with {resp.status_code}")
        except Exception as e:
            print(f"⚠ Command Center connection failed: {e}")
            print(f"  Make sure CC is running on your laptop: python scripts/run_command_center.py")
            print(f"  Events will not reach webapp, but demo will continue.")
    else:
        print("Command Center: OFF (no --cc specified)")

    # Start camera feed in background (pulls from local bridge)
    start_camera_feed(bridge_url="http://127.0.0.1:9090")

    code_dir = os.path.dirname(os.path.abspath(__file__))

    input("\nPress ENTER to start the sequence (robot will move!)...")
    print()

    try:
        initial_contact = ""
        
        # Skip to triage if requested (for practice)
        if args.start_triage:
            print("\n" + "=" * 50)
            print("  PRACTICE MODE: Starting at triage")
            print("=" * 50)
            cc_status("Practice: starting at triage", "TRIAGE")
        else:
            # ── Phase 1: Call out ─────────────────────────────────
            cc_status("Searching for survivors", "SEARCH")

            if do_voice:
                speak("Hello? Is anyone there? Can anyone hear me?", "SEARCH")
                conversation_transcript.append("Robot: Hello? Is anyone there? Can anyone hear me?")
                
                # Use smart listen with retry for initial contact
                response = listen_with_retry(max_duration_s=3.0, retries=1)
                initial_contact = response or "(no response)"
                if response:
                    conversation_transcript.append(f"Victim: {response}")

                if response:
                    speak("I can hear you! Hold on, I'm coming to help!", "SEARCH")
                    conversation_transcript.append("Robot: I can hear you! Hold on, I'm coming to help!")
                else:
                    speak("I think I heard something. I'm coming over!", "SEARCH")
                    conversation_transcript.append("Robot: I think I heard something. I'm coming over!")

            # ── Phase 2: Walk ─────────────────────────────────────
            if do_walk:
                cc_status("Walking to victim", "NAVIGATE")

                print("\n>> PREPARE MODE")
                client.ChangeMode(RobotMode.kPrepare)
                time.sleep(2)  # reduced from 3s

                print(">> WALKING MODE")
                client.ChangeMode(RobotMode.kWalking)
                time.sleep(1)  # reduced from 2s

                walk_forward(client, 5)
                time.sleep(0.3)  # reduced from 1s
                turn_left(client)
                time.sleep(0.3)  # reduced from 1s
                walk_forward(client, 3)
                time.sleep(0.3)  # reduced from 1s
                turn_left(client)
                time.sleep(0.3)  # reduced from 1s
                stop(client)

            # ── Phase 3: Remove debris (demo4 keyframe) ───────────
            cc_status("Clearing debris", "CLEAR_DEBRIS")

            if do_voice:
                speak("I'm here. Hold still, I'm clearing the debris.", "CLEAR_DEBRIS")
                conversation_transcript.append("Robot: I'm here. Hold still, I'm clearing the debris.")

            play_keyframe("demo4", code_dir)
            time.sleep(0.3)  # minimal pause after keyframe

        # ── Phase 4: Smart LLM Medical Triage ─────────────────
        cc_status("Conducting medical triage", "TRIAGE")

        if do_voice:
            speak("Debris cleared. I'm a medical rescue robot. Let me check on you.", "TRIAGE")
            conversation_transcript.append("Robot: Debris cleared. I'm a medical rescue robot. Let me check on you.")
            # No extra sleep - triage function handles all timing
            
            # Choose triage mode
            if args.hardcode_transcript:
                triage_answers = run_hardcoded_triage()  # FAST: pre-scripted, no waiting
            else:
                triage_answers = run_triage_dialogue()   # SMART: real LLM conversation
        else:
            # If voice disabled, skip triage
            triage_answers = {}

        # ── Phase 5: Head keyframe (scan/look around) ─────────
        cc_status("Scanning area for documentation", "SCAN")
        
        if do_voice:
            speak("I'm going to look around and document your injuries for the medical team.", "SCAN")
            conversation_transcript.append("Robot: I'm going to look around and document your injuries for the medical team.")
        
        play_keyframe("head", code_dir)
        time.sleep(0.3)  # minimal pause after head scan

        # ── Phase 6: Build full medical report ────────────────
        cc_status("Generating medical report", "REPORT")
        
        report_path = None
        try:
            from himpublic.medical.triage_pipeline import TriagePipeline
            
            reports_dir = Path(code_dir).parent / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            # Speech-only triage (no CV/YOLO) - faster, no GPU needed
            pipeline = TriagePipeline(output_dir=str(reports_dir), use_pose=False)
            
            report_path = pipeline.build_report(
                scene_summary="Walk demo v4: voice-guided rescue with LLM-powered triage assessment by humanoid robot.",
                victim_answers=triage_answers,
                notes=["Generated from walk_demo_v4.py", "Speech-first triage with dialogue manager"],
                conversation_transcript=conversation_transcript,
                scene_images=[],  # Could add captured frames here if available
                meta={"demo": "walk_v4", "initial_contact": initial_contact},
            )
            
            if report_path:
                print(f"\n✓ Medical report generated: {report_path}")
                
                # Post report to command center
                if CC_URL:
                    try:
                        with open(report_path, "r") as f:
                            report_doc = f.read()
                        http_requests.post(
                            f"{CC_URL}/report",
                            json={
                                "incident_id": f"walk_v4_{int(time.time())}",
                                "timestamp": time.time(),
                                "patient_summary": triage_answers,
                                "document": report_doc,
                                "transcript": conversation_transcript,
                                "report_path": report_path,
                            },
                            timeout=5,
                        )
                        print("✓ Report posted to command center.")
                    except Exception as e:
                        print(f"⚠ Command center post failed: {e}")
        except Exception as e:
            print(f"⚠ Report generation failed: {e}")
            # Fallback: save simple JSON
            fallback = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "initial_contact": initial_contact,
                "triage_answers": triage_answers,
                "transcript": conversation_transcript,
            }
            fallback_path = os.path.join(code_dir, f"triage_simple_{time.strftime('%Y%m%d_%H%M%S')}.json")
            with open(fallback_path, "w") as f:
                json.dump(fallback, f, indent=2)
            print(f"✓ Fallback report saved: {fallback_path}")

        # ── Done ──────────────────────────────────────────────
        cc_status("Assessment complete, holding position", "COMPLETE")

        if do_voice:
            speak("Help is on the way. Stay calm, I'm staying right here with you.", "COMPLETE")
            conversation_transcript.append("Robot: Help is on the way. Stay calm, I'm staying right here with you.")

        stop(client)
        
        # Print summary
        print("\n" + "=" * 50)
        print("  TRIAGE SUMMARY")
        print("=" * 50)
        for key, val in triage_answers.items():
            label = key.replace("_", " ").title()
            print(f"  {label}: {val}")
        print("=" * 50)

        print("\n✓ Done. Ctrl+C to exit.")
        while True:
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nStopping.")
        stop_camera_feed()
        stop(client)
    except Exception as e:
        print(f"\nError: {e}")
        stop_camera_feed()
        stop(client)
        raise


if __name__ == "__main__":
    main()
