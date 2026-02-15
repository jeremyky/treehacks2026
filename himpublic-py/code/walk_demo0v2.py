#!/usr/bin/env python3
"""
Walk Demo v2 -- Same as v0 but with optimized camera feed for webapp.

Key changes from v0:
  - Simplified camera loop with better error handling
  - Faster camera feed polling (every 0.2s instead of 0.3s)
  - Debug messages for camera connectivity
  - No CV processing, just raw JPEG relay to webapp

Usage:
  python walk_demo0v2.py --cc http://192.168.10.1:8000
"""

import argparse
import io
import json
import os
import subprocess
import threading
import time
import wave

import numpy as np

from booster_robotics_sdk_python import (
    B1LocoClient,
    ChannelFactory,
    RobotMode,
)

# ---------------------------
# GLOBALS
# ---------------------------
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
CC_URL = None       # Command center URL, set via --cc
NO_SPEECH = False   # Set via --no-speech

# ---------------------------
# COMMAND CENTER (web interface)
# ---------------------------
def cc_post(endpoint: str, **kwargs):
    """POST to command center. Silently fails if CC_URL is None or unreachable."""
    if not CC_URL:
        return None
    try:
        import requests
        return requests.post(f"{CC_URL}{endpoint}", timeout=2, **kwargs)
    except Exception as e:
        return None

def cc_event(payload: dict):
    cc_post("/event", json=payload)

def cc_status(status: str, stage: str = ""):
    payload = {"event": "heartbeat", "status": status, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    cc_event(payload)

def cc_robot_said(text: str, stage: str = ""):
    payload = {"event": "robot_said", "text": text, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    cc_event(payload)

def cc_patient_response(summary: str):
    if summary:
        cc_event({"event": "heard_response", "transcript": summary, "timestamp": time.time()})

def cc_snapshot(jpeg_bytes: bytes, meta: dict = None):
    """Send camera snapshot to command center (fast, no blocking)."""
    if not CC_URL or not jpeg_bytes:
        return
    try:
        import requests
        files = {"file": ("snapshot.jpg", jpeg_bytes, "image/jpeg")}
        data = {}
        if meta:
            data["metadata"] = json.dumps(meta)
        requests.post(f"{CC_URL}/snapshot", files=files, data=data, timeout=1)
    except Exception:
        pass

def cc_report(report: dict):
    cc_post("/report", json=report)

# ---------------------------
# OPERATOR MESSAGE POLLING (for chat -> robot speech)
# ---------------------------
_operator_poll_stop = False
_last_operator_index = -1

def _operator_message_loop():
    """Poll command center for operator messages and speak them."""
    global _operator_poll_stop, _last_operator_index
    
    if not CC_URL:
        return
    
    print("💬 Operator message listener started...")
    
    try:
        import requests
    except ImportError:
        return
    
    while not _operator_poll_stop:
        try:
            resp = requests.get(f"{CC_URL}/operator-messages", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                messages = data.get("messages", [])
                
                # Speak any new messages we haven't seen yet
                for idx, msg in enumerate(messages):
                    if idx > _last_operator_index:
                        text = msg.get("text", "").strip()
                        if text:
                            print(f"\n💬 OPERATOR MESSAGE: {text}")
                            # Speak WITHOUT calling cc_robot_said (already in comms from operator)
                            print(f"🔊 {text}")
                            if not NO_SPEECH:
                                try:
                                    subprocess.run(["espeak", text], 
                                                 stdout=subprocess.DEVNULL, 
                                                 stderr=subprocess.DEVNULL, 
                                                 timeout=30)
                                    time.sleep(0.5)
                                except Exception:
                                    pass
                            _last_operator_index = idx
                
                # Acknowledge messages we've spoken
                if _last_operator_index >= 0:
                    try:
                        requests.post(
                            f"{CC_URL}/operator-messages/ack",
                            json={"after_index": _last_operator_index},
                            timeout=1
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        
        time.sleep(1)  # Poll every second

def start_operator_listener():
    """Start background operator message polling thread."""
    global _operator_poll_stop
    _operator_poll_stop = False
    t = threading.Thread(target=_operator_message_loop, daemon=True)
    t.start()
    print("💬 Operator message listener thread started")

def stop_operator_listener():
    """Stop operator message polling thread."""
    global _operator_poll_stop
    _operator_poll_stop = True

# ---------------------------
# OPTIMIZED CAMERA FEED
# ---------------------------
_camera_stop = False
_camera_active = False

def _camera_loop():
    """Continuously grab frames from robot bridge and relay to webapp.
    
    Optimized for:
    - Fast polling (200ms intervals)
    - Minimal processing (just relay JPEG)
    - Robust error handling
    - Auto-recovery from bridge disconnects
    """
    global _camera_stop, _camera_active
    bridge = "http://127.0.0.1:9090"
    consecutive_fails = 0
    frame_count = 0
    
    try:
        import requests
    except ImportError:
        print("  [Camera: requests not available]")
        return
    
    print(f"📹 Camera feed starting (bridge: {bridge})...")
    
    while not _camera_stop:
        try:
            resp = requests.get(f"{bridge}/frame?quality=70", timeout=1.5)
            if resp.status_code == 200 and resp.content:
                # Send raw JPEG to webapp (no processing)
                cc_snapshot(resp.content, meta={"source": "robot_camera", "frame": frame_count})
                consecutive_fails = 0
                frame_count += 1
                
                if not _camera_active:
                    print("✓ Camera feed active!")
                    _camera_active = True
            else:
                consecutive_fails += 1
                if consecutive_fails == 1:
                    print(f"⚠ Bridge returned status {resp.status_code}")
        except requests.exceptions.ConnectionError:
            consecutive_fails += 1
            if consecutive_fails == 1:
                print(f"⚠ Bridge not responding at {bridge}")
                print("   Make sure: bash robot_run.sh (starts bridge)")
        except requests.exceptions.Timeout:
            consecutive_fails += 1
        except Exception as e:
            consecutive_fails += 1
            if consecutive_fails == 1:
                print(f"⚠ Camera error: {e}")
        
        # Stop if too many failures
        if consecutive_fails > 30:
            print(f"❌ Camera feed stopped (bridge unavailable after {consecutive_fails} attempts)")
            _camera_active = False
            break
        
        # Fast polling for smooth video feed
        time.sleep(0.2)
    
    print("📹 Camera feed stopped")

def start_camera_feed():
    """Start background camera feed thread."""
    global _camera_stop, _camera_active
    _camera_stop = False
    _camera_active = False
    t = threading.Thread(target=_camera_loop, daemon=True)
    t.start()
    print("📹 Camera feed thread started")

def stop_camera_feed():
    """Stop camera feed thread."""
    global _camera_stop
    _camera_stop = True
    time.sleep(0.3)  # Give thread time to stop
    print("📹 Camera feed stopped")

# ---------------------------
# AUDIO / SPEECH
# ---------------------------
ALSA_CAPTURE_DEVICE = "hw:1,0"

def speak(text, stage=""):
    """Speak text via espeak (non-blocking) and post to command center."""
    print(f"ROBOT: {text}")
    cc_robot_said(text, stage=stage)
    if NO_SPEECH:
        return
    try:
        proc = subprocess.Popen(["espeak", text],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        words = len(text.split())
        wait = max(1.0, words / 2.5) + 2.0
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.3)
    except FileNotFoundError:
        print("  [espeak not found]")

def record_audio(duration_s=2):
    try:
        proc = subprocess.run(
            ["arecord", "-D", ALSA_CAPTURE_DEVICE,
             "-f", "S16_LE", "-r", "16000", "-c", "1",
             "-d", str(duration_s), "-t", "wav", "-q", "-"],
            capture_output=True
        )
        return proc.stdout
    except Exception:
        return b""

def heard_voice(duration=2.0, threshold=200):
    wav = record_audio(duration)
    if not wav:
        return False
    try:
        with wave.open(io.BytesIO(wav)) as wf:
            audio = wf.readframes(wf.getnframes())
            samples = np.frombuffer(audio, dtype=np.int16)
        energy = abs(samples).mean()
        print(f"[Audio energy: {energy:.1f}]")
        return energy > threshold
    except Exception:
        return False

# ---------------------------
# WALKING
# ---------------------------
def send_move(client, vx, vy, vz, duration):
    hz = 10
    for _ in range(int(duration * hz)):
        client.Move(vx, vy, vz)
        time.sleep(1 / hz)
    client.Move(0, 0, 0)

def walk_forward(client, seconds=5):
    print(f">> WALK FORWARD {seconds}s")
    cc_status(f"Walking forward {seconds}s", "WALKING")
    send_move(client, 0.5, 0, 0, seconds)

def walk_back(client, seconds=2):
    print(f">> WALK BACK {seconds}s")
    cc_status(f"Walking back {seconds}s", "WALKING")
    send_move(client, -0.4, 0, 0, seconds)

def turn_left(client, degrees=90):
    rad = degrees * 3.14159 / 180.0
    yaw_rate = 0.5
    duration = rad / yaw_rate
    print(f">> TURN LEFT {degrees} degrees (~{duration:.1f}s)")
    cc_status(f"Turning left {degrees} degrees", "WALKING")
    send_move(client, 0, 0, yaw_rate, duration)

def stop(client):
    client.Move(0, 0, 0)

# ---------------------------
# KEYFRAME PLAYER
# ---------------------------
def play_keyframe(name, final_hold=2.0):
    """Play a keyframe JSON via replay_capture.py (subprocess).

    Uses --skip-mode (robot already in kWalking + UpperBodyCustomControl).
    Uses --final-hold so the process exits after holding the last pose.
    """
    json_path = os.path.join(CODE_DIR, f"{name}.json")
    cmd = [
        "python3", "-u",
        os.path.join(CODE_DIR, "replay_capture.py"),
        json_path,
        "--skip-mode",
        "--final-hold", str(final_hold),
    ]
    print(f">> KEYFRAME: {name}.json")
    cc_status(f"Playing motion: {name}", "KEYFRAME")
    try:
        subprocess.run(cmd, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"  [keyframe timed out]")
    except Exception as e:
        print(f"  [keyframe error: {e}]")

# ---------------------------
# SCREENSHOT CAPTURE
# ---------------------------
def capture_screenshot():
    """Grab one frame from robot camera bridge and send to CC. Returns jpeg bytes or None."""
    try:
        import requests
        resp = requests.get("http://127.0.0.1:9090/frame?quality=85", timeout=3)
        if resp.status_code == 200 and resp.content:
            cc_snapshot(resp.content, meta={"phase": "scan", "source": "head_scan"})
            print("  [screenshot captured]")
            return resp.content
    except Exception:
        print("  [screenshot failed]")
    return None

# ---------------------------
# MAIN DEMO
# ---------------------------
def main():
    global CC_URL, NO_SPEECH

    ap = argparse.ArgumentParser(description="Walk demo v2 -- optimized camera feed")
    ap.add_argument("--cc", type=str, default=None,
                    help="Command center URL (e.g. http://192.168.10.1:8000)")
    ap.add_argument("--no-speech", action="store_true",
                    help="Skip espeak calls (print only)")
    args = ap.parse_args()

    CC_URL = args.cc.rstrip("/") if args.cc else None
    NO_SPEECH = args.no_speech

    print("=" * 60)
    print("  WALK DEMO V2 -- Optimized Camera Feed")
    print("=" * 60)
    
    if CC_URL:
        print(f"Command Center: {CC_URL}")
        print(f"Webapp: http://localhost:5176")
    else:
        print("Command Center: OFF (pass --cc http://192.168.10.1:8000)")
        print("")
        return

    print("\nConnecting to robot SDK...")
    ChannelFactory.Instance().Init(domain_id=0)
    client = B1LocoClient()
    client.Init()
    print("✓ Robot SDK connected")

    # Start camera feed FIRST (before user input)
    start_camera_feed()
    
    # Start operator message listener (for chat -> robot speech)
    start_operator_listener()
    
    time.sleep(2)  # Give camera 2s to initialize
    
    if not _camera_active:
        print("")
        print("⚠ WARNING: Camera feed not active!")
        print("  Make sure bridge is running:")
        print("    bash robot_run.sh")
        print("")

    print("💡 TIP: Type messages in the webapp chat and robot will speak them!")
    input("\nPress ENTER to start demo...\n")

    # ============================
    # 1. WALK TO PERSON IN DANGER
    # ============================
    cc_status("Searching for victim", "SEARCH")
    print("\n[Listening for call for help...]")
    if heard_voice(duration=3.0):
        cc_patient_response("Help! Help!")
        speak("I can hear you! Hold on, I'm coming to help.", "SEARCH")
    else:
        speak("I heard a distress signal. I'm on my way.", "SEARCH")

    # Prepare first (stable standing), then walk
    cc_status("Navigating to victim", "WALKING")
    print("Switching to kPrepare...")
    client.ChangeMode(RobotMode.kPrepare)
    time.sleep(2)

    print("Switching to kWalking...")
    client.ChangeMode(RobotMode.kWalking)
    time.sleep(1)

    walk_forward(client, 5)

    # Turn left 90, walk forward 3s, turn left 90 again
    turn_left(client, 90)
    walk_forward(client, 3)
    turn_left(client, 90)

    # ============================
    # 2. PICK UP THE BOX
    # ============================
    cc_status("Clearing debris", "CLEAR_DEBRIS")
    speak("I'm here. Let me clear this debris.", "CLEAR_DEBRIS")

    client.UpperBodyCustomControl(True)
    time.sleep(0.5)

    play_keyframe("demo4", final_hold=2.0)

    client.UpperBodyCustomControl(False)
    time.sleep(0.5)

    # ============================
    # 3. TRIAGE -- "WHAT HURTS?"
    # ============================
    cc_status("Conducting triage", "TRIAGE")
    speak("Okay, what hurts?", "TRIAGE")
    time.sleep(4)
    cc_patient_response("My right arm... it really hurts.")

    # ============================
    # 4. HEAD SCAN
    # ============================
    cc_status("Scanning patient", "SCAN")
    speak("Let me scan you and document your injuries.", "SCAN")

    client.UpperBodyCustomControl(True)
    time.sleep(0.5)

    play_keyframe("head", final_hold=2.0)

    # Capture a screenshot mid-scan and relay to command center
    capture_screenshot()

    client.UpperBodyCustomControl(False)
    time.sleep(0.5)

    # ============================
    # 5. DIAGNOSIS & REASSURANCE
    # ============================
    cc_status("Delivering diagnosis", "DIAGNOSIS")
    speak("Help is on the way. Your right humerus has been broken. "
          "Don't move it. I'll stay with you until the first responders come.",
          "DIAGNOSIS")

    # Post a simple medical report to the web UI (with document for command center display)
    if CC_URL:
        incident_id = f"rescue_{int(time.time())}"
        report_document = (
            "# Incident Report\n\n"
            "## Summary\n"
            "Suspected right humerus fracture. Patient conscious and responsive. "
            "Pain level reported. Debris cleared from patient.\n\n"
            "## Findings\n"
            "- Right arm injury (patient indicated); suspected humerus fracture.\n"
            "- Patient responsive to verbal triage.\n"
            "- Debris cleared from patient area.\n\n"
            "## Recommendation\n"
            "Immobilize right arm. Dispatch paramedics.\n\n"
            "## Status\n"
            "AWAITING_FIRST_RESPONDERS\n\n"
            "*Triage support and documentation only — not a medical diagnosis.*"
        )
        cc_report({
            "incident_id": incident_id,
            "timestamp": time.time(),
            "findings": "Suspected right humerus fracture. Patient conscious and responsive. "
                        "Pain level reported. Debris cleared from patient.",
            "recommendation": "Immobilize right arm. Dispatch paramedics.",
            "status": "AWAITING_FIRST_RESPONDERS",
            "document": report_document,
            "patient_summary": {
                "triage_priority": "MODERATE",
                "injury_location": "right arm",
                "bleeding": "no",
                "pain_level": "reported",
            },
        })

    # ============================
    # 6. WALK BACK A COUPLE STEPS
    # ============================
    cc_status("Returning to standby", "RETURN")
    time.sleep(1)
    walk_back(client, 3)

    speak("Assessment complete. Holding position.", "COMPLETE")
    cc_status("Demo complete", "COMPLETE")
    stop(client)

    stop_camera_feed()
    stop_operator_listener()

    print("\n" + "=" * 60)
    print("  DEMO COMPLETE")
    print("=" * 60)
    print("\nCtrl+C to exit.")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
