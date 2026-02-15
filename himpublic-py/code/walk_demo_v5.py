#!/usr/bin/env python3
"""
Walk Demo V5 — Hardcoded transcript + Screenshots during head scan only.

Flow:
  1. "Is anyone there?" → hardcoded response
  2. Walk: forward 5, left, forward 3, left
  3. demo4 keyframe (remove debris)
  4. Hardcoded triage conversation (FAST - no mic, no LLM)
  5. Head keyframe + capture screenshots (for medical report)
  6. Generate medical report with transcript + screenshots

NO mic delays, NO LLM delays, NO CV - just fast demo execution with real movement + screenshots.

Usage (on robot):
    cd ~/Workspace/himpublic/code
    python3 walk_demo_v5.py --cc http://LAPTOP_IP:8000
    python3 walk_demo_v5.py --cc http://LAPTOP_IP:8000 --no-walk     # skip walking
    python3 walk_demo_v5.py --cc http://LAPTOP_IP:8000 --start-triage # skip walk + debris
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

# Add himpublic to path for report generation
_SCRIPT_DIR = Path(__file__).resolve().parent
_HIMPUBLIC_SRC = _SCRIPT_DIR.parent / "src"
if str(_HIMPUBLIC_SRC) not in sys.path:
    sys.path.insert(0, str(_HIMPUBLIC_SRC))

# ── Walk tunables ────────────────────────────────────────────────
CFG = {
    "walk_speed": 0.5,
    "turn_speed": 0.4,
    "step_length": 0.50,
    "turn_90_time": 3.9,
}

# ── Command center URL (set via --cc flag) ───────────────────────
CC_URL = None

# ── Conversation storage ──────────────────────────────────────────
conversation_transcript = []
triage_answers = {}
scan_image_paths = []

# ── Hardcoded triage script (bleeding-focused, right leg) ────────
HARDCODED_SCRIPT = [
    # Search/arrival phase
    ("Robot", "Hello, is anyone there? Can anyone hear me?"),
    ("Victim", "Help! I'm here!"),
    ("Robot", "I can hear you! Hold on, I'm coming to help. Keep talking so I can find you."),
    ("Victim", "Over here!"),
    ("Robot", "I'm here. Try not to move. I'm going to clear the debris."),
    ("Robot", "Debris cleared. I'm a medical rescue robot. I'm going to check on you now."),
    ("Robot", "I'm going to ask quick questions and document injuries for the medical team."),
    # Triage assessment
    ("Robot", "Are you hurt? Do you need help?"),
    ("Victim", "Yes, I need help."),
    ("Robot", "Understood."),
    ("Robot", "Where are you bleeding? Tell me the body part and left or right."),
    ("Victim", "My right leg is bleeding."),
    ("Robot", "Right leg bleeding noted."),
    ("Robot", "Is the bleeding heavy—soaking through—yes or no?"),
    ("Victim", "Yes—pretty heavy."),
    ("Robot", "Heavy bleeding noted. Prioritizing bleeding control."),
    ("Robot", "Can you press firmly on the wound with cloth or your wrap—yes or no?"),
    ("Victim", "Yes, I'm pressing on it with the wrap."),
    ("Robot", "Good. Keep firm pressure."),
    ("Robot", "Do you have severe pain in the right leg from 0 to 10?"),
    ("Victim", "Eight out of ten."),
    ("Robot", "Pain score recorded."),
    ("Robot", "Can you wiggle your toes on the right foot—yes or no?"),
    ("Victim", "Yes."),
    ("Robot", "Toe movement present."),
    ("Robot", "Do you feel numbness or tingling in your right foot—yes or no?"),
    ("Victim", "No."),
    ("Robot", "No numbness noted."),
    ("Robot", "Can you stand or put weight on the right leg—yes or no?"),
    ("Victim", "No, I can't stand on it."),
    ("Robot", "Unable to bear weight noted—possible fracture."),
    # Wrap-up
    ("Robot", "I'm going to look around and document your injuries for the medical team."),
    ("Robot", "Assessment complete. Holding position."),
    ("Robot", "Help is on the way. Stay calm. I'm staying right here with you."),
]


# =====================================================================
#  Command Center helpers
# =====================================================================
def cc_post_event(payload: dict):
    if not CC_URL:
        return
    try:
        http_requests.post(f"{CC_URL}/event", json=payload, timeout=3)
    except Exception:
        pass


def cc_robot_said(text: str, stage: str = ""):
    payload = {"event": "robot_said", "text": text, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    cc_post_event(payload)


def cc_heard(transcript: str):
    if transcript:
        cc_post_event({"event": "heard_response", "transcript": transcript, "timestamp": time.time()})


def cc_status(status: str, stage: str = ""):
    payload = {"event": "heartbeat", "status": status, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    cc_post_event(payload)


def cc_post_snapshot(jpeg_bytes: bytes, meta: dict = None):
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
#  Background camera feed → command center (faster updates)
# =====================================================================
_camera_thread = None
_camera_stop = False
_bridge_url = None


def camera_capture_loop():
    global _camera_stop, _bridge_url
    if not _bridge_url:
        return
    
    local_bridge = "http://127.0.0.1:9090"
    consecutive_failures = 0
    
    try:
        while not _camera_stop:
            try:
                resp = http_requests.get(f"{local_bridge}/frame?quality=70", timeout=2)
                if resp.status_code == 200 and resp.content:
                    cc_post_snapshot(resp.content, meta={"source": "robot_camera"})
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures > 10:
                        break
            except Exception:
                consecutive_failures += 1
                if consecutive_failures > 10:
                    break
            time.sleep(0.3)  # fast updates
    except Exception:
        pass


def start_camera_feed(bridge_url: str = None):
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
    print(f"🔊 {text}")
    cc_robot_said(text, stage=stage)
    try:
        subprocess.run(["espeak", text], timeout=10, check=False)
    except Exception as e:
        print(f"  [TTS error: {e}]")


# =====================================================================
#  Hardcoded triage (FAST)
# =====================================================================
def run_hardcoded_triage():
    global triage_answers, conversation_transcript
    
    print("\n" + "=" * 50)
    print("  TRIAGE (Hardcoded - FAST)")
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
            time.sleep(0.3)  # just enough for TTS
        else:
            print(f"  [Victim: {text}]")
            cc_heard(text)
            time.sleep(0.1)
        conversation_transcript.append(f"{role}: {text}")
    
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
    send_move(client, CFG["walk_speed"], 0.0, 0.0, dur, f"WALK FORWARD {n_steps} steps")


def turn_left(client):
    send_move(client, 0.0, 0.0, CFG["turn_speed"], CFG["turn_90_time"], "TURN LEFT 90°")


def stop(client):
    print(">> STOP")
    client.Move(0.0, 0.0, 0.0)


# =====================================================================
#  Keyframe player + screenshot capture
# =====================================================================
def play_keyframe_with_screenshots(keyframe_name: str, code_dir: str, capture: bool = False) -> list[str]:
    """
    Play keyframe and optionally capture screenshots during it.
    Returns list of screenshot paths.
    """
    candidates = [f"{keyframe_name}.json"]
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
        print(f"   ⚠ Keyframe '{keyframe_name}' not found")
        return []
    
    print(f"\n>> KEYFRAME: {os.path.basename(keyframe_file)}")
    
    screenshots = []
    
    # If capturing, grab frames from bridge during keyframe playback
    if capture:
        capture_thread_running = True
        capture_count = [0]  # mutable for thread
        
        def capture_during_keyframe():
            local_bridge = "http://127.0.0.1:9090"
            output_dir = Path(code_dir).parent / "reports" / "scan_frames"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time())
            
            while capture_thread_running:
                try:
                    resp = http_requests.get(f"{local_bridge}/frame?quality=85", timeout=2)
                    if resp.status_code == 200 and resp.content:
                        frame_num = capture_count[0]
                        filepath = output_dir / f"head_scan_{timestamp}_{frame_num:02d}.jpg"
                        filepath.write_bytes(resp.content)
                        screenshots.append(str(filepath))
                        capture_count[0] += 1
                        print(f"   📸 Captured frame {frame_num + 1}")
                        cc_post_snapshot(resp.content, meta={"phase": "scan", "frame": frame_num})
                except Exception:
                    pass
                time.sleep(0.5)  # capture every 0.5s for more frames
        
        capture_thread = threading.Thread(target=capture_during_keyframe, daemon=True)
        capture_thread.start()
    
    try:
        proc = subprocess.Popen(
            [
                sys.executable, "-u",
                os.path.join(code_dir, "replay_capture.py"),
                keyframe_file,
                "--override-hold", "0.3",
                "--override-move", "0.15",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text:
                print(f"   {text}")
            if "Holding last keyframe" in text:
                time.sleep(1)
                proc.kill()
                proc.wait()
                print(f"   ✓ Keyframe complete!")
                break
        proc.wait()
    except Exception as e:
        print(f"   ⚠ Keyframe error: {e}")
    finally:
        if capture:
            capture_thread_running = False
            time.sleep(0.5)  # let last capture finish
    
    return screenshots


# =====================================================================
#  Main
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="Walk demo v5 (hardcoded + screenshots)")
    parser.add_argument("--network", default="")
    parser.add_argument("--cc", type=str, default="", help="Command center URL")
    parser.add_argument("--no-walk", action="store_true")
    parser.add_argument("--start-triage", action="store_true", help="Skip walk+debris")
    parser.add_argument("--walk-speed", type=float, default=0.5)
    parser.add_argument("--turn-time", type=float, default=3.9)
    args = parser.parse_args()

    CFG["walk_speed"] = args.walk_speed
    CFG["turn_90_time"] = args.turn_time

    global CC_URL, conversation_transcript, triage_answers, scan_image_paths
    CC_URL = args.cc.rstrip("/") if args.cc else None
    conversation_transcript = []
    triage_answers = {}
    scan_image_paths = []

    do_walk = not args.no_walk

    print("=" * 50)
    print("  WALK DEMO V5 — Hardcoded + Screenshots")
    print(f"  Command Center: {CC_URL or 'OFF'}")
    print("=" * 50)

    print("Connecting to robot SDK...")
    ChannelFactory.Instance().Init(domain_id=0, network_interface=args.network)
    client = B1LocoClient()
    client.Init()
    print("Connected!\n")

    # Start camera feed
    start_camera_feed(bridge_url="http://127.0.0.1:9090")

    code_dir = os.path.dirname(os.path.abspath(__file__))

    input("Press ENTER to start...\n")

    try:
        initial_contact = "I'm here"
        
        if args.start_triage:
            print("\n" + "=" * 50)
            print("  PRACTICE: Starting at triage")
            print("=" * 50)
        else:
            # ── Phase 1: Call out ───────────────────────────
            cc_status("Searching for survivors", "SEARCH")
            speak("Hello? Is anyone there? Can anyone hear me?", "SEARCH")
            conversation_transcript.append("Robot: Hello? Is anyone there? Can anyone hear me?")
            time.sleep(0.3)
            
            # Hardcoded response (instant)
            print("  [Victim: I'm here!]")
            cc_heard("I'm here!")
            conversation_transcript.append("Victim: I'm here!")
            
            speak("I can hear you! Hold on, I'm coming to help!", "SEARCH")
            conversation_transcript.append("Robot: I can hear you! Hold on, I'm coming to help!")

            # ── Phase 2: Walk ──────────────────────────────
            if do_walk:
                cc_status("Walking to victim", "NAVIGATE")
                
                print("\n>> PREPARE MODE")
                client.ChangeMode(RobotMode.kPrepare)
                time.sleep(2)
                
                print(">> WALKING MODE")
                client.ChangeMode(RobotMode.kWalking)
                time.sleep(1)
                
                walk_forward(client, 5)
                time.sleep(0.3)
                turn_left(client)
                time.sleep(0.3)
                walk_forward(client, 3)
                time.sleep(0.3)
                turn_left(client)
                time.sleep(0.3)
                stop(client)

            # ── Phase 3: Remove debris (demo4) ─────────────
            cc_status("Clearing debris", "CLEAR_DEBRIS")
            speak("I'm here. Hold still, I'm clearing the debris.", "CLEAR_DEBRIS")
            conversation_transcript.append("Robot: I'm here. Hold still, I'm clearing the debris.")
            time.sleep(0.3)
            
            play_keyframe_with_screenshots("demo4", code_dir, capture=False)
            time.sleep(0.3)

        # ── Phase 4: Hardcoded triage (FAST) ───────────────
        cc_status("Conducting triage", "TRIAGE")
        speak("Debris cleared. I'm a medical rescue robot. Let me check on you.", "TRIAGE")
        conversation_transcript.append("Robot: Debris cleared. I'm a medical rescue robot. Let me check on you.")
        time.sleep(0.3)
        
        # Hardcoded triage answers (bleeding-focused, right leg)
        triage_answers = {
            "injury_location": "right leg",
            "bleeding": "yes (heavy)",
            "bleeding_location": "right leg",
            "bleeding_severity": "heavy",
            "direct_pressure": "yes",
            "pain_level": "8",
            "can_wiggle_toes_right": "yes",
            "numbness_right_foot": "no",
            "can_bear_weight_right": "no",
            "suspected_fracture": "possible (unable to bear weight)",
            "mechanism": "roof debris / heavy object impact",
        }
        
        for role, text in HARDCODED_SCRIPT:
            if role == "Robot":
                speak(text, stage="TRIAGE")
                time.sleep(0.3)
            else:
                print(f"  [Victim: {text}]")
                cc_heard(text)
                time.sleep(0.1)
            conversation_transcript.append(f"{role}: {text}")

        # ── Phase 5: Head scan + SCREENSHOTS ───────────────
        cc_status("Scanning and documenting", "SCAN")
        speak("I'm going to look around and document your injuries for the medical team.", "SCAN")
        conversation_transcript.append("Robot: I'm going to look around and document your injuries for the medical team.")
        time.sleep(0.3)
        
        # Capture screenshots DURING head keyframe
        print("\n" + "=" * 50)
        print("  CAPTURING SCREENSHOTS DURING HEAD SCAN")
        print("=" * 50)
        all_scan_frames = play_keyframe_with_screenshots("head", code_dir, capture=True)
        print(f"✓ Captured {len(all_scan_frames)} screenshots")
        
        # Select best frames for medical report (middle frames most likely to show injury)
        if len(all_scan_frames) >= 3:
            # Use middle frames (most likely to show the red band/injury)
            mid_idx = len(all_scan_frames) // 2
            scan_image_paths = all_scan_frames[mid_idx-1:mid_idx+2]  # 3 frames around middle
            print(f"✓ Selected frames {mid_idx} to {mid_idx+2} for medical report (best injury visibility)")
        elif all_scan_frames:
            scan_image_paths = all_scan_frames
        else:
            scan_image_paths = []
            print("⚠ No screenshots captured")

        # ── Phase 6: Generate medical report ───────────────
        cc_status("Generating report", "REPORT")
        
        try:
            from himpublic.medical.triage_pipeline import TriagePipeline
            
            reports_dir = Path(code_dir).parent / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            pipeline = TriagePipeline(output_dir=str(reports_dir), use_pose=False)
            
            report_path = pipeline.build_report(
                scene_summary="Roof debris collapse with direct impact to right lower extremity. Victim found supine with heavy object on leg; debris cleared by robot. Active bleeding from right leg (heavy, victim applying pressure). Suspected fracture or crush injury (pain 8/10, unable to bear weight). Neurovascular: toe movement present, no numbness. Patient conscious and responsive.",
                victim_answers=triage_answers,
                notes=[
                    "Mechanism: roof/debris collapse with heavy object impact",
                    "Primary: Active external bleeding (right leg, heavy)",
                    "Secondary: Suspected right lower-extremity fracture or crush injury",
                    "Evidence: High pain (8/10), unable to bear weight, victim applying direct pressure",
                    "Neurovascular check: toe movement present, no numbness/tingling",
                    "Priority: HIGH (heavy bleeding + possible fracture)",
                    "Hardcoded transcript for demo consistency",
                    "Screenshots captured during head scan keyframe",
                ],
                conversation_transcript=conversation_transcript,
                scene_images=scan_image_paths,
                meta={
                    "demo": "walk_v5",
                    "initial_contact": initial_contact,
                    "mechanism": "debris_collapse",
                    "primary_injury": "right_leg_bleeding_heavy",
                    "secondary_injury": "suspected_fracture_crush",
                    "triage_priority": "HIGH",
                },
            )
            
            if report_path:
                print(f"\n✓ Medical report: {report_path}")
                
                if CC_URL:
                    try:
                        with open(report_path, "r") as f:
                            report_doc = f.read()
                        http_requests.post(
                            f"{CC_URL}/report",
                            json={
                                "incident_id": f"walk_v5_{int(time.time())}",
                                "timestamp": time.time(),
                                "patient_summary": triage_answers,
                                "document": report_doc,
                                "transcript": conversation_transcript,
                                "images": scan_image_paths,
                                "report_path": report_path,
                            },
                            timeout=5,
                        )
                        print("✓ Report posted to command center")
                    except Exception as e:
                        print(f"⚠ CC post failed: {e}")
        except Exception as e:
            print(f"⚠ Report generation failed: {e}")

        # ── Done ───────────────────────────────────────────
        cc_status("Complete", "DONE")
        speak("Help is on the way. I'm staying right here with you.", "DONE")
        stop(client)

        print("\n" + "=" * 50)
        print("  SUMMARY")
        print("=" * 50)
        for k, v in triage_answers.items():
            print(f"  {k}: {v}")
        print(f"  Screenshots: {len(scan_image_paths)}")
        print("=" * 50)
        print("\n✓ Demo complete. Ctrl+C to exit.")
        
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
