#!/usr/bin/env python3
"""
Final Demo -- Bleeding-focused rescue scenario with medical report.

Flow:
  1. Search: "Is anyone there?" → hardcoded victim response
  2. Walk to victim (forward 5s, turn left, forward 3s, turn left)
  3. Clear debris (demo4 keyframe)
  4. Bleeding-focused triage (hardcoded Q&A)
  5. Head scan (head keyframe) + capture screenshots
  6. Generate medical report with screenshots
  7. Post to webapp
  8. Walk back

Features:
  - Hardcoded transcript (no mic/transcription delays)
  - Live camera feed to webapp
  - Screenshot capture during head scan
  - Medical report generation with images
  - Full webapp integration
"""

import argparse
import json
import os
import sys
import threading
import time
import subprocess
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

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
CC_URL = None  # Set via --cc flag
NO_SPEECH = False  # Set via --no-speech flag
CODE_DIR = os.path.dirname(os.path.abspath(__file__))

# Conversation storage
conversation_transcript = []
triage_answers = {}
scan_image_paths = []

# Hardcoded bleeding-focused transcript (simplified)
HARDCODED_SCRIPT = [
    # Search/arrival
    ("Robot", "Hello, is anyone there? Can anyone hear me?", "Patient calls for help"),
    ("Robot", "I can hear you! Hold on, I'm coming to help.", "Patient responds"),
    ("Robot", "I'm here. Try not to move. I'm going to clear the debris.", None),
    ("Robot", "Debris cleared. I'm a medical rescue robot.", None),
    # Simplified triage (key questions only)
    ("Robot", "Where are you hurt?", "Patient indicates right leg"),
    ("Robot", "Are you bleeding?", "Patient confirms bleeding"),
    ("Robot", "On a scale of one to ten, how bad is the pain?", "Patient reports pain level 8"),
    ("Robot", "Can you move your toes?", "Patient confirms toe movement"),
    # Wrap-up
    ("Robot", "I'm going to document your injuries for the medical team.", None),
    ("Robot", "Help is on the way. Stay calm.", None),
]

# ═══════════════════════════════════════════════════════════════════
#  COMMAND CENTER INTEGRATION
# ═══════════════════════════════════════════════════════════════════
def cc_post_event(payload: dict):
    if not CC_URL:
        return
    try:
        http_requests.post(f"{CC_URL}/event", json=payload, timeout=3)
    except Exception:
        pass

def cc_robot_said(text: str, stage: str = ""):
    if not CC_URL:
        return
    payload = {"event": "robot_said", "text": text, "timestamp": time.time()}
    if stage:
        payload["stage"] = stage
    try:
        http_requests.post(f"{CC_URL}/event", json=payload, timeout=3)
    except Exception as e:
        print(f"  [CC comms failed: {e}]")

def cc_patient_response(summary: str):
    """Post patient response summary to command center (displayed as 'Patient: ...')"""
    if not CC_URL or not summary:
        return
    try:
        http_requests.post(f"{CC_URL}/event", json={
            "event": "heard_response",
            "transcript": summary,
            "timestamp": time.time()
        }, timeout=3)
    except Exception as e:
        print(f"  [CC comms failed: {e}]")

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
        http_requests.post(f"{CC_URL}/snapshot", files=files, data=data, timeout=3)
    except Exception as e:
        # Silently fail but log first error
        pass

# ═══════════════════════════════════════════════════════════════════
#  BACKGROUND CAMERA FEED
# ═══════════════════════════════════════════════════════════════════
_camera_thread = None
_camera_stop = False

def camera_capture_loop():
    global _camera_stop
    local_bridge = "http://127.0.0.1:9090"
    consecutive_failures = 0
    
    print("📹 Starting camera feed (using bridge at 127.0.0.1:9090)...")
    
    try:
        while not _camera_stop:
            try:
                resp = http_requests.get(f"{local_bridge}/frame?quality=70", timeout=2)
                if resp.status_code == 200 and resp.content:
                    cc_post_snapshot(resp.content, meta={"source": "robot_camera"})
                    consecutive_failures = 0
                    if consecutive_failures == 0:  # First success
                        print("✓ Camera feed active")
                else:
                    consecutive_failures += 1
                    if consecutive_failures == 1:
                        print(f"⚠ Bridge not responding (status {resp.status_code})")
                    if consecutive_failures > 20:
                        print("⚠ Camera feed stopped (bridge unavailable)")
                        break
            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures == 1:
                    print(f"⚠ Camera error: {e}")
                    print("   Make sure bridge is running: python -m himpublic.io.robot_bridge")
                if consecutive_failures > 20:
                    print("⚠ Camera feed stopped (too many failures)")
                    break
            time.sleep(0.3)
    except Exception:
        pass

def start_camera_feed():
    global _camera_thread, _camera_stop
    _camera_stop = False
    _camera_thread = threading.Thread(target=camera_capture_loop, daemon=True)
    _camera_thread.start()

def stop_camera_feed():
    global _camera_stop
    _camera_stop = True

# ═══════════════════════════════════════════════════════════════════
#  SPEECH
# ═══════════════════════════════════════════════════════════════════
def speak(text: str, stage: str = ""):
    print(f"🔊 {text}")
    cc_robot_said(text, stage=stage)
    if NO_SPEECH:
        return
    try:
        # Calculate estimated speech duration (rough: 150 words per minute = 2.5 words/sec)
        words = len(text.split())
        estimated_duration = max(1.0, words / 2.5)
        
        subprocess.run(["espeak", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        time.sleep(0.5)  # Brief pause after speech finishes
    except FileNotFoundError:
        print("  [espeak not found, skipping speech]")
        time.sleep(estimated_duration)  # Simulate speech timing
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
#  WALKING
# ═══════════════════════════════════════════════════════════════════
def send_move(client, vx, vy, vz, duration, label=""):
    if label:
        print(f"\n>> {label}")
    hz = 10
    for _ in range(int(duration * hz)):
        client.Move(vx, vy, vz)
        time.sleep(1 / hz)
    client.Move(0, 0, 0)

def walk_forward(client, seconds=5):
    send_move(client, 0.5, 0, 0, seconds, f"WALK FORWARD {seconds}s")

def walk_back(client, seconds=2):
    send_move(client, -0.4, 0, 0, seconds, f"WALK BACK {seconds}s")

def turn_left(client, degrees=90):
    """Turn left by rotating in place. ~0.5 rad/s yaw rate."""
    rad = degrees * 3.14159 / 180.0
    yaw_rate = 0.5  # rad/s
    duration = rad / yaw_rate
    send_move(client, 0, 0, yaw_rate, duration, f"TURN LEFT {degrees}°")

def stop(client):
    print(">> STOP")
    client.Move(0, 0, 0)


# ═══════════════════════════════════════════════════════════════════
#  KEYFRAME PLAYER + SCREENSHOT CAPTURE
# ═══════════════════════════════════════════════════════════════════
def play_keyframe(name, final_hold=2.0, capture_screenshots=False):
    """Play a keyframe JSON via replay_capture.py, optionally capturing screenshots.
    
    Returns: list of screenshot paths if capturing, empty list otherwise.
    """
    json_path = os.path.join(CODE_DIR, f"{name}.json")
    if not os.path.exists(json_path):
        print(f"   ⚠ Keyframe '{name}.json' not found")
        return []
    
    print(f"\n>> KEYFRAME: {name}.json")
    
    screenshots = []
    capture_thread_running = False
    
    # If capturing, start background thread to grab frames during keyframe
    if capture_screenshots:
        capture_thread_running = True
        capture_count = [0]
        
        def capture_during_keyframe():
            nonlocal screenshots
            local_bridge = "http://127.0.0.1:9090"
            output_dir = Path(CODE_DIR).parent / "reports" / "scan_frames"
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
                time.sleep(0.5)
        
        capture_thread = threading.Thread(target=capture_during_keyframe, daemon=True)
        capture_thread.start()
    
    # Play keyframe
    cmd = [
        "python3", os.path.join(CODE_DIR, "replay_capture.py"),
        json_path,
        "--skip-mode",
        "--final-hold", str(final_hold),
    ]
    
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        if capture_screenshots:
            capture_thread_running = False
            time.sleep(0.5)
    
    return screenshots


# ═══════════════════════════════════════════════════════════════════
#  MAIN DEMO
# ═══════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Final demo -- bleeding-focused rescue")
    ap.add_argument("--cc", type=str, default="", help="Command center URL (e.g. http://LAPTOP_IP:8000)")
    ap.add_argument("--no-speech", action="store_true", help="Skip espeak calls (print only)")
    ap.add_argument("--start-triage", action="store_true", help="Skip walking, start at triage")
    args = ap.parse_args()

    global CC_URL, NO_SPEECH, conversation_transcript, triage_answers, scan_image_paths
    CC_URL = args.cc.rstrip("/") if args.cc else None
    NO_SPEECH = args.no_speech
    conversation_transcript = []
    triage_answers = {}
    scan_image_paths = []

    print("=" * 60)
    print("  FINAL DEMO — Bleeding-focused rescue")
    print(f"  Command Center: {CC_URL or 'OFF'}")
    print("=" * 60)
    
    # Clean up old reports from previous runs
    print("\n🧹 Cleaning up old reports...")
    reports_dir = Path(CODE_DIR).parent / "reports"
    if reports_dir.exists():
        try:
            # Delete old triage reports (keep only last 5)
            triage_mds = sorted(reports_dir.glob("triage_*.md"))
            triage_pdfs = sorted(reports_dir.glob("triage_*.pdf"))
            for old_file in triage_mds[:-5] + triage_pdfs[:-5]:
                old_file.unlink()
                print(f"  Deleted: {old_file.name}")
            
            # Delete old scan frames
            scan_frames_dir = reports_dir / "scan_frames"
            if scan_frames_dir.exists():
                for old_frame in scan_frames_dir.glob("*.jpg"):
                    old_frame.unlink()
                print(f"  Cleared scan frames")
            
            # Delete old evidence folders (keep only last 3)
            evidence_dir = reports_dir / "evidence"
            if evidence_dir.exists():
                old_evidence = sorted([d for d in evidence_dir.iterdir() if d.is_dir()])
                for old_dir in old_evidence[:-3]:
                    import shutil
                    shutil.rmtree(old_dir)
                    print(f"  Deleted: {old_dir.name}")
                
                # Delete loose evidence files
                for old_file in evidence_dir.glob("*.jpg"):
                    old_file.unlink()
            
            print("✓ Cleanup complete\n")
        except Exception as e:
            print(f"⚠ Cleanup warning: {e}\n")

    print("\nConnecting to robot SDK...")
    ChannelFactory.Instance().Init(domain_id=0)
    client = B1LocoClient()
    client.Init()
    print("Connected!\n")

    # Start camera feed
    start_camera_feed()

    input("Press ENTER to start...\n")

    try:
        if args.start_triage:
            print("\n" + "=" * 60)
            print("  PRACTICE: Starting at triage")
            print("=" * 60)
        else:
            # ══════════════════════════════════════════════════════════
            # PHASE 1: SEARCH
            # ══════════════════════════════════════════════════════════
            cc_status("Searching for survivors", "SEARCH")
            
            # First call out
            speak("Hello, is anyone there? Can anyone hear me?", "SEARCH")
            conversation_transcript.append("Robot: Hello, is anyone there? Can anyone hear me?")
            time.sleep(0.5)
            
            # Patient response appears in command center
            print("  [Patient responds...]")
            cc_patient_response("Patient calls for help")
            conversation_transcript.append("Victim: Help! I'm here!")
            
            # Robot hears and responds
            speak("I can hear you! Hold on, I'm coming to help. Keep talking so I can find you.", "SEARCH")
            conversation_transcript.append("Robot: I can hear you! Hold on, I'm coming to help. Keep talking so I can find you.")
            time.sleep(0.3)
            
            # Patient response appears in command center
            print("  [Patient responds...]")
            cc_patient_response("Patient responds")
            conversation_transcript.append("Victim: Over here!")

            # ══════════════════════════════════════════════════════════
            # PHASE 2: WALK TO VICTIM
            # ══════════════════════════════════════════════════════════
            cc_status("Walking to victim", "NAVIGATE")
            
            # Stop camera feed during walking to prevent thread interference
            print("⏸  Pausing camera feed for precise movement")
            stop_camera_feed()
            time.sleep(0.5)
            
            print("\n>> PREPARE MODE")
            client.ChangeMode(RobotMode.kPrepare)
            time.sleep(2)
            
            print(">> WALKING MODE")
            client.ChangeMode(RobotMode.kWalking)
            time.sleep(1)
            
            walk_forward(client, 5)
            turn_left(client, 90)
            walk_forward(client, 3)
            turn_left(client, 90)
            
            # Resume camera feed after walking
            print("▶️  Resuming camera feed")
            start_camera_feed()

            # ══════════════════════════════════════════════════════════
            # PHASE 3: CLEAR DEBRIS
            # ══════════════════════════════════════════════════════════
            cc_status("Clearing debris", "CLEAR_DEBRIS")
            speak("I'm here. Try not to move. I'm going to clear the debris.", "CLEAR_DEBRIS")
            conversation_transcript.append("Robot: I'm here. Try not to move. I'm going to clear the debris.")
            
            client.UpperBodyCustomControl(True)
            time.sleep(0.5)
            
            play_keyframe("demo4", final_hold=2.0, capture_screenshots=False)
            
            client.UpperBodyCustomControl(False)
            time.sleep(0.5)

        # ══════════════════════════════════════════════════════════
        # PHASE 4: TRIAGE (HARDCODED)
        # ══════════════════════════════════════════════════════════
        cc_status("Conducting triage", "TRIAGE")
        speak("Debris cleared. I'm a medical rescue robot. I'm going to check on you now.", "TRIAGE")
        conversation_transcript.append("Robot: Debris cleared. I'm a medical rescue robot. I'm going to check on you now.")
        time.sleep(0.3)
        
        # Hardcoded triage answers
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
            "triage_priority": "HIGH",
        }
        
        # Run through hardcoded script (robot speaks, patient responses appear in command center)
        print("\n" + "=" * 60)
        print("  TRIAGE CONVERSATION")
        print("=" * 60)
        
        pending_patient_response = None
        pending_patient_text = None
        
        for role, robot_text, patient_summary in HARDCODED_SCRIPT[2:]:  # Skip search lines (already done)
            # Post PREVIOUS patient response when robot starts NEXT question
            if pending_patient_response:
                print(f"  [Patient responds...]")
                cc_patient_response(pending_patient_response)
                if pending_patient_text:
                    conversation_transcript.append(pending_patient_text)
                time.sleep(0.3)  # Brief pause after showing patient response
            
            # Robot speaks (only audio output) - wait for speech to complete
            speak(robot_text, stage="TRIAGE")
            conversation_transcript.append(f"Robot: {robot_text}")
            
            # Store patient response to show BEFORE next robot question
            if patient_summary:
                pending_patient_response = patient_summary
                # Prepare detailed answer for transcript
                if "right leg" in patient_summary:
                    pending_patient_text = "Victim: My right leg."
                elif "bleeding" in patient_summary:
                    pending_patient_text = "Victim: Yes, bleeding."
                elif "pain level 8" in patient_summary:
                    pending_patient_text = "Victim: Eight."
                elif "toe movement" in patient_summary:
                    pending_patient_text = "Victim: Yes, I can move them."
                else:
                    pending_patient_text = None
                time.sleep(0.8)  # Pause as if patient is thinking/responding
            else:
                pending_patient_response = None
                pending_patient_text = None
        
        # Post final patient response if there is one
        if pending_patient_response:
            print(f"  [Patient responds...]")
            cc_patient_response(pending_patient_response)
            if pending_patient_text:
                conversation_transcript.append(pending_patient_text)
            time.sleep(0.3)

        # ══════════════════════════════════════════════════════════
        # PHASE 5: HEAD SCAN + SCREENSHOT AT MIDDLE
        # ══════════════════════════════════════════════════════════
        cc_status("Scanning and documenting", "SCAN")
        
        client.UpperBodyCustomControl(True)
        time.sleep(0.5)
        
        print("\n" + "=" * 60)
        print("  HEAD SCAN + SCREENSHOT AT MIDDLE")
        print("=" * 60)
        
        # Start head keyframe in background
        import threading
        keyframe_done = [False]
        
        def run_head_keyframe():
            play_keyframe("head", final_hold=2.0, capture_screenshots=False)
            keyframe_done[0] = True
        
        keyframe_thread = threading.Thread(target=run_head_keyframe, daemon=True)
        keyframe_thread.start()
        
        # Wait for middle of keyframe (approximately 3-4 seconds into the motion)
        time.sleep(3.5)
        
        # Capture ONE screenshot at the middle
        all_scan_frames = []
        try:
            resp = http_requests.get("http://127.0.0.1:9090/frame?quality=85", timeout=2)
            if resp.status_code == 200 and resp.content:
                output_dir = Path(CODE_DIR).parent / "reports" / "scan_frames"
                output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = int(time.time())
                filepath = output_dir / f"head_scan_{timestamp}_middle.jpg"
                filepath.write_bytes(resp.content)
                all_scan_frames.append(str(filepath))
                print(f"✓ Captured middle frame screenshot")
                cc_post_snapshot(resp.content, meta={"phase": "scan", "frame": "middle"})
        except Exception as e:
            print(f"⚠ Screenshot failed: {e}")
        
        # Wait for keyframe to finish
        keyframe_thread.join(timeout=10)
        
        client.UpperBodyCustomControl(False)
        time.sleep(0.5)
        
        # ══════════════════════════════════════════════════════════
        # PHASE 5.5: RED DETECTION ONLY
        # ══════════════════════════════════════════════════════════
        print("\n" + "=" * 60)
        print("  DETECTING RED IN SCREENSHOT")
        print("=" * 60)
        
        scan_image_paths = []
        annotated_images = []
        
        if all_scan_frames:
            try:
                import cv2
                import numpy as np
                
                img_path = all_scan_frames[0]
                frame = cv2.imread(img_path)
                
                if frame is not None:
                    # Convert to HSV for red detection
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                    
                    # Red color ranges (two ranges because red wraps around in HSV)
                    lower_red1 = np.array([0, 100, 100])
                    upper_red1 = np.array([10, 255, 255])
                    lower_red2 = np.array([160, 100, 100])
                    upper_red2 = np.array([180, 255, 255])
                    
                    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
                    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
                    red_mask = mask1 | mask2
                    
                    # Find contours of red regions
                    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    if contours:
                        # Find largest red region
                        largest_contour = max(contours, key=cv2.contourArea)
                        area = cv2.contourArea(largest_contour)
                        
                        if area > 500:  # Minimum area threshold
                            # Get bounding box
                            x, y, w, h = cv2.boundingRect(largest_contour)
                            
                            # Create annotated version
                            annotated = frame.copy()
                            cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 0, 255), 3)
                            cv2.putText(annotated, "BLEEDING DETECTED", (x, y-10),
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                            
                            # Save annotated image
                            output_dir = Path(CODE_DIR).parent / "reports" / "evidence"
                            output_dir.mkdir(parents=True, exist_ok=True)
                            timestamp = int(time.time())
                            annotated_path = output_dir / f"red_detected_{timestamp}.jpg"
                            cv2.imwrite(str(annotated_path), annotated)
                            
                            print(f"✓ Red detected! Area: {area:.0f} pixels")
                            print(f"✓ Saved annotated image: {annotated_path}")
                            
                            scan_image_paths = [str(annotated_path)]
                            annotated_images = [str(annotated_path)]
                        else:
                            print(f"⚠ Red area too small ({area:.0f} pixels), using original")
                            scan_image_paths = [img_path]
                    else:
                        print("⚠ No red detected, using original screenshot")
                        scan_image_paths = [img_path]
                else:
                    print("⚠ Could not load screenshot")
                        
            except Exception as e:
                print(f"⚠ Red detection failed: {e}")
                scan_image_paths = all_scan_frames
        else:
            print("⚠ No screenshots captured")
        
        print(f"✓ Using {len(scan_image_paths)} image(s) for medical report")

        # ══════════════════════════════════════════════════════════
        # PHASE 6: GENERATE MEDICAL REPORT
        # ══════════════════════════════════════════════════════════
        cc_status("Generating report", "REPORT")
        
        try:
            from himpublic.medical.triage_pipeline import TriagePipeline
            
            reports_dir = Path(CODE_DIR).parent / "reports"
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
                    "demo": "final_demo",
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
                        
                        # Get PDF path if it exists
                        pdf_path = str(report_path).replace(".md", ".pdf")
                        pdf_exists = Path(pdf_path).exists()
                        
                        http_requests.post(
                            f"{CC_URL}/report",
                            json={
                                "incident_id": f"final_demo_{int(time.time())}",
                                "timestamp": time.time(),
                                "patient_summary": triage_answers,
                                "document": report_doc,
                                "transcript": conversation_transcript,
                                "images": scan_image_paths,
                                "annotated_images": annotated_images,
                                "report_path": report_path,
                                "pdf_path": pdf_path if pdf_exists else None,
                            },
                            timeout=5,
                        )
                        print("✓ Report posted to command center")
                    except Exception as e:
                        print(f"⚠ CC post failed: {e}")
        except Exception as e:
            print(f"⚠ Report generation failed: {e}")

        # ══════════════════════════════════════════════════════════
        # PHASE 7: WALK BACK & HOLD POSITION
        # ══════════════════════════════════════════════════════════
        cc_status("Complete", "DONE")
        speak("Help is on the way. Stay calm. I'm staying right here with you.", "DONE")
        
        # Stop camera for precise walk back
        stop_camera_feed()
        time.sleep(0.5)
        
        time.sleep(1)
        walk_back(client, 3)
        
        # Resume camera
        start_camera_feed()
        
        speak("Assessment complete. Holding position.", "DONE")
        stop(client)

        # Summary
        print("\n" + "=" * 60)
        print("  SUMMARY")
        print("=" * 60)
        for k, v in triage_answers.items():
            print(f"  {k}: {v}")
        print(f"  Screenshots: {len(scan_image_paths)}")
        print("=" * 60)
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
