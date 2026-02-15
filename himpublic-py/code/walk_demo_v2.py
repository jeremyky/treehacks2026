#!/usr/bin/env python3
"""
Walk Demo V2 — Voice + Walking + Punch + Smart Triage + Command Center.

Flow:
  1. "Is anyone there?" → listen → "I'm coming!"
  2. Walk: forward 5, left, forward 3, left
  3. Remove debris (punch keyframe)
  4. Medical triage with smart keyword responses
  5. All speech + transcripts streamed to command center webapp

Usage (on robot):
    cd ~/Workspace/himpublic/code
    export OPENAI_API_KEY='sk-...'
    python3 walk_demo_v2.py --cc http://YOUR_LAPTOP_IP:8000
    python3 walk_demo_v2.py --cc http://YOUR_LAPTOP_IP:8000 --no-walk
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

import requests as http_requests

from booster_robotics_sdk_python import (
    B1LocoClient,
    ChannelFactory,
    RobotMode,
)

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
TRIAGE_REPORT = {
    "timestamp": "",
    "initial_contact": "",
    "name": "",
    "injury_location": "",
    "pain_level": "",
    "breathing": "",
    "feeling_legs": "",
    "keywords_detected": [],
}

# ── Keyword → response templates ─────────────────────────────────
KEYWORD_RESPONSES = {
    "head":       "Head injuries can be serious. Try not to move your head.",
    "neck":       "Don't move your neck. We'll stabilize it when the team arrives.",
    "chest":      "Try to keep breathing slowly and evenly.",
    "stomach":    "Try not to move. Keep pressure on it if you can.",
    "back":       "Don't try to sit up or twist. Keep your spine straight.",
    "arm":        "Try to keep your arm still. Don't put weight on it.",
    "hand":       "Keep your hand elevated if you can.",
    "leg":        "Don't try to stand. Keep your leg as still as possible.",
    "knee":       "Don't bend it. We'll splint it when help arrives.",
    "foot":       "Don't put any weight on it.",
    "ankle":      "Keep it elevated. Don't try to walk.",
    "bleeding":   "Apply pressure to the wound if you can. Help is coming.",
    "blood":      "Apply pressure to stop the bleeding. Stay calm.",
    "dizzy":      "Stay lying down. Don't try to sit up.",
    "numb":       "Don't try to move. The medical team will check that.",
    "broken":     "Don't move it. We'll splint it when help arrives.",
    "trapped":    "I'm working on getting you free. Stay calm.",
    "breath":     "Focus on slow, steady breaths.",
    "can't move": "Don't force it. The medical team will help you.",
    "pain":       "I understand. Try to stay as still as you can.",
    "10":         "That's very severe. Pain relief is coming. Hold on.",
    "9":          "That's very high. Stay still, pain relief is coming.",
    "8":          "I understand that's a lot of pain. Breathe steadily.",
    "7":          "Noted. The medical team will address your pain.",
    "yes":        "Okay, noted.",
    "no":         "Okay, understood.",
    "help":       "Help is on the way. You're not alone.",
}
DEFAULT_RESPONSE = "Okay, I've noted that. The medical team will be informed."


# =====================================================================
#  Command Center — post events so the webapp shows everything live
# =====================================================================
def cc_post_event(payload: dict):
    """POST to command center /event. Silently fails if CC not set."""
    if not CC_URL:
        return
    try:
        http_requests.post(f"{CC_URL}/event", json=payload, timeout=3)
    except Exception:
        pass  # don't let CC errors break the demo


def cc_robot_said(text: str, stage: str = ""):
    """Tell command center the robot said something."""
    payload = {"event": "robot_said", "text": text, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    cc_post_event(payload)


def cc_heard(transcript: str):
    """Tell command center what was heard."""
    if transcript:
        cc_post_event({
            "event": "heard_response",
            "transcript": transcript,
            "timestamp": time.time(),
        })


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
        http_requests.post(f"{CC_URL}/snapshot", files=files, data=data, timeout=5)
    except Exception:
        pass


# =====================================================================
#  Background camera feed → command center
# =====================================================================
BRIDGE_URL = "http://localhost:9090"
_feed_stop = threading.Event()


def _camera_feed_loop():
    """Background thread: grab frame from bridge server, POST to command center."""
    while not _feed_stop.is_set():
        try:
            resp = http_requests.get(f"{BRIDGE_URL}/frame", timeout=2)
            if resp.status_code == 200 and resp.content:
                cc_post_snapshot(resp.content)
        except Exception:
            pass
        _feed_stop.wait(1.0)  # post a frame every 1 second


def start_camera_feed():
    """Start background camera streaming to command center."""
    if not CC_URL:
        return
    t = threading.Thread(target=_camera_feed_loop, daemon=True)
    t.start()
    print("Camera feed streaming to command center.\n")


def stop_camera_feed():
    _feed_stop.set()


# =====================================================================
#  TTS
# =====================================================================
def speak(text: str, stage: str = ""):
    print(f"\n🔊 ROBOT: {text}")
    cc_robot_said(text, stage)
    try:
        espeak = subprocess.Popen(
            ["espeak", "--stdout", "-a", "200", "-s", "140", text],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        paplay = subprocess.Popen(
            ["paplay"], stdin=espeak.stdout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        espeak.stdout.close()
        paplay.communicate(timeout=30)
        espeak.wait(timeout=5)
    except Exception as e:
        print(f"  [TTS error: {e}]")


# =====================================================================
#  Record + Transcribe
# =====================================================================
def record_audio(duration_s: float = 2.0) -> bytes:
    print(f"🎤 LISTENING ({duration_s:.0f}s)...")
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
    if not wav_bytes:
        return ""
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
                print(f"👂 HEARD: {text}")
            return text
        finally:
            os.unlink(tmp)
    except Exception as e:
        print(f"  [transcribe error: {e}]")
        return ""


def listen(duration_s: float = 2.0) -> str:
    wav = record_audio(duration_s)
    time.sleep(0.2)
    text = transcribe(wav)
    cc_heard(text)
    return text


# =====================================================================
#  Smart response
# =====================================================================
def pick_response(transcript: str) -> str:
    if not transcript:
        return ""
    lower = transcript.lower()
    matched = []
    for kw in KEYWORD_RESPONSES:
        if kw in lower:
            matched.append(kw)
    TRIAGE_REPORT["keywords_detected"].extend(matched)
    if matched:
        best = max(matched, key=len)
        return KEYWORD_RESPONSES[best]
    return DEFAULT_RESPONSE


def ask_and_respond(question: str, report_key: str):
    speak(question, stage="TRIAGE")
    answer = listen(2.0)
    TRIAGE_REPORT[report_key] = answer or "(no response)"
    if answer:
        response = pick_response(answer)
        speak(response, stage="TRIAGE")
    return answer or ""


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
#  Main
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="Walk demo v2")
    parser.add_argument("--network", default="")
    parser.add_argument("--cc", type=str, default="",
                        help="Command center URL, e.g. http://192.168.1.5:8000")
    parser.add_argument("--no-walk", action="store_true")
    parser.add_argument("--no-voice", action="store_true")
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

    TRIAGE_REPORT["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 50)
    print("  WALK DEMO V2")
    print(f"  Command Center: {CC_URL or 'OFF'}")
    print("=" * 50)

    # Connect
    print("Connecting to robot SDK...")
    ChannelFactory.Instance().Init(domain_id=0, network_interface=args.network)
    client = B1LocoClient()
    client.Init()
    print("Connected!\n")

    # Start camera feed in background
    start_camera_feed()

    input("Press ENTER to start...")
    print()

    try:
        # ── Phase 1: Call out ─────────────────────────────────
        cc_status("Searching for survivors", "SEARCH")

        if do_voice:
            speak("Hello? Is anyone there? Can anyone hear me?", "SEARCH")
            time.sleep(0.5)
            response = listen(2.0)
            TRIAGE_REPORT["initial_contact"] = response or "(no response)"

            if response:
                speak("I can hear you! Hold on, I'm coming to help!", "SEARCH")
            else:
                speak("I think I heard something. I'm coming over!", "SEARCH")
            time.sleep(0.5)

        # ── Phase 2: Walk ─────────────────────────────────────
        if do_walk:
            cc_status("Walking to victim", "NAVIGATE")

            print("\n>> PREPARE MODE")
            client.ChangeMode(RobotMode.kPrepare)
            time.sleep(3)

            print(">> WALKING MODE")
            client.ChangeMode(RobotMode.kWalking)
            time.sleep(2)

            walk_forward(client, 5)
            time.sleep(1)
            turn_left(client)
            time.sleep(1)
            walk_forward(client, 3)
            time.sleep(1)
            turn_left(client)
            time.sleep(1)
            stop(client)

        # ── Phase 3: Remove debris (punch) ────────────────────
        cc_status("Clearing debris", "CLEAR_DEBRIS")

        if do_voice:
            speak("I'm here. Hold still, I'm clearing the debris.", "CLEAR_DEBRIS")
            time.sleep(0.5)

        print("\n>> PLAYING PUNCH")
        code_dir = os.path.dirname(os.path.abspath(__file__))
        punch_file = None
        for name in ["punch.json", "punch4.json", "punch3.json", "punch2.json", "punch-v0.json"]:
            p = os.path.join(code_dir, name)
            if os.path.exists(p):
                punch_file = p
                break

        if punch_file:
            print(f"   Using: {punch_file}")
            # replay_capture.py holds forever after last keyframe — we watch
            # stdout for "Holding last keyframe" then kill it
            proc = subprocess.Popen(
                [
                    sys.executable, "-u",  # unbuffered output
                    os.path.join(code_dir, "replay_capture.py"),
                    punch_file,
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
                    print("   Punch complete!")
                    break
            else:
                # Process ended on its own
                proc.wait()
                print(f"   replay_capture.py exited with code {proc.returncode}")
        else:
            print("   No punch file found — skipping")

        time.sleep(2)

        # ── Phase 4: Medical triage ───────────────────────────
        cc_status("Conducting medical triage", "TRIAGE")

        if do_voice:
            speak("Debris cleared. I'm a medical rescue robot. Let me check on you.", "TRIAGE")
            time.sleep(0.3)

            ask_and_respond("Can you tell me your name?", "name")
            ask_and_respond("Where are you hurt?", "injury_location")
            ask_and_respond("On a scale of 1 to 10, how bad is the pain?", "pain_level")
            ask_and_respond("Are you having trouble breathing?", "breathing")
            ask_and_respond("Can you feel your legs?", "feeling_legs")

        # ── Done ──────────────────────────────────────────────
        cc_status("Assessment complete, holding position", "COMPLETE")

        if do_voice:
            speak("Help is on the way. Stay calm, I'm staying right here with you.", "COMPLETE")

        stop(client)

        # ── Save & post triage report ─────────────────────────
        print("\n" + "=" * 50)
        print("  TRIAGE REPORT")
        print("=" * 50)
        for key, val in TRIAGE_REPORT.items():
            label = key.replace("_", " ").title()
            if isinstance(val, list):
                val = ", ".join(val) if val else "(none)"
            print(f"  {label}: {val}")
        print("=" * 50)

        report_path = os.path.join(code_dir, f"triage_report_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(report_path, "w") as f:
            json.dump(TRIAGE_REPORT, f, indent=2)
        print(f"\nReport saved: {report_path}")

        # Post report to command center
        if CC_URL:
            try:
                http_requests.post(f"{CC_URL}/report", json=TRIAGE_REPORT, timeout=5)
                print("Report sent to command center.")
            except Exception:
                pass

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
