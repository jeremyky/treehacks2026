#!/usr/bin/env python3
"""
Test script to generate and post a demo medical report to command center.
Run this to test the webapp display without running the full robot demo.
"""

import sys
import time
from pathlib import Path
import requests

# Add himpublic to path
_SCRIPT_DIR = Path(__file__).resolve().parent
_HIMPUBLIC_SRC = _SCRIPT_DIR / "src"
if str(_HIMPUBLIC_SRC) not in sys.path:
    sys.path.insert(0, str(_HIMPUBLIC_SRC))

from himpublic.medical.triage_pipeline import TriagePipeline
import cv2
import numpy as np

CC_URL = "http://localhost:8000"

print("=" * 60)
print("  TEST REPORT GENERATOR")
print("=" * 60)
print()

# Create a dummy screenshot with "BLEEDING DETECTED" annotation
print("📸 Creating test screenshot with bleeding detection...")
test_img = np.ones((480, 640, 3), dtype=np.uint8) * 220  # Light gray background
# Draw a red box (simulating bleeding)
cv2.rectangle(test_img, (200, 150), (400, 350), (0, 0, 200), -1)  # Red filled rectangle
cv2.rectangle(test_img, (200, 150), (400, 350), (0, 0, 255), 3)  # Red border
cv2.putText(test_img, "BLEEDING DETECTED", (210, 130), 
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
cv2.putText(test_img, "Right Leg - Heavy Bleeding", (220, 240),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

# Save test screenshot
evidence_dir = Path("reports/evidence")
evidence_dir.mkdir(parents=True, exist_ok=True)
test_screenshot = evidence_dir / f"test_bleeding_{int(time.time())}.jpg"
cv2.imwrite(str(test_screenshot), test_img)
print(f"✓ Test screenshot: {test_screenshot}")
print()

# Create demo triage data
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

conversation_transcript = [
    "Robot: Hello, is anyone there?",
    "Victim: Help! I'm here!",
    "Robot: I can hear you! I'm coming to help.",
    "Robot: Where are you hurt?",
    "Victim: My right leg.",
    "Robot: Are you bleeding?",
    "Victim: Yes, bleeding.",
    "Robot: On a scale of 1-10, how bad is the pain?",
    "Victim: Eight.",
    "Robot: Can you move your toes?",
    "Victim: Yes, I can move them.",
    "Robot: I'm documenting your injuries.",
    "Robot: Help is on the way.",
]

print("📝 Generating test medical report...")

reports_dir = Path("reports")
reports_dir.mkdir(parents=True, exist_ok=True)

pipeline = TriagePipeline(output_dir=str(reports_dir), use_pose=False)

report_path = pipeline.build_report(
    scene_summary="TEST REPORT - Roof debris collapse with direct impact to right lower extremity. Victim found supine with heavy object on leg; debris cleared by robot. Active bleeding from right leg (heavy, victim applying pressure). Suspected fracture or crush injury (pain 8/10, unable to bear weight). Neurovascular: toe movement present, no numbness. Patient conscious and responsive.",
    victim_answers=triage_answers,
    notes=[
        "⚠️ THIS IS A TEST REPORT FOR DEMO PURPOSES",
        "Mechanism: roof/debris collapse with heavy object impact",
        "Primary: Active external bleeding (right leg, heavy)",
        "Secondary: Suspected right lower-extremity fracture or crush injury",
        "Evidence: High pain (8/10), unable to bear weight, victim applying direct pressure",
        "Neurovascular check: toe movement present, no numbness/tingling",
        "Priority: HIGH (heavy bleeding + possible fracture)",
    ],
    conversation_transcript=conversation_transcript,
    scene_images=[str(test_screenshot)],  # Include test screenshot
    meta={
        "demo": "test_report",
        "mechanism": "debris_collapse",
        "primary_injury": "right_leg_bleeding_heavy",
        "secondary_injury": "suspected_fracture_crush",
        "triage_priority": "HIGH",
    },
)

if report_path:
    print(f"✓ Report generated: {report_path}")
    
    # Check for PDF
    pdf_path = str(report_path).replace(".md", ".pdf")
    pdf_exists = Path(pdf_path).exists()
    if pdf_exists:
        print(f"✓ PDF generated: {pdf_path}")
    
    # Post to command center
    print(f"\n📤 Posting to command center at {CC_URL}...")
    try:
        with open(report_path, "r") as f:
            report_doc = f.read()
        
        response = requests.post(
            f"{CC_URL}/report",
            json={
                "incident_id": f"test_demo_{int(time.time())}",
                "timestamp": time.time(),
                "patient_summary": triage_answers,
                "document": report_doc,
                "transcript": conversation_transcript,
                "images": [],
                "annotated_images": [],
                "report_path": report_path,
                "pdf_path": pdf_path if pdf_exists else None,
            },
            timeout=5,
        )
        
        if response.status_code == 200:
            print("✓ Report posted successfully!")
            print()
            print("=" * 60)
            print("  SUCCESS!")
            print("=" * 60)
            print()
            print("🌐 Check the webapp: http://localhost:5176/")
            print()
            print("You should see:")
            print("  ✓ Injury Report box showing: Priority HIGH, right leg, etc.")
            print("  ✓ Full report at bottom with download buttons")
            print("  ✓ Click 📄 PDF or 📝 MD to download")
            print()
        else:
            print(f"⚠ Post failed: HTTP {response.status_code}")
            print(f"Response: {response.text}")
    except requests.exceptions.ConnectionRefusedError:
        print("❌ Command center not running!")
        print()
        print("Start it with: ./start_demo.sh")
        print("Or manually: python scripts/run_command_center.py")
    except Exception as e:
        print(f"❌ Post failed: {e}")
else:
    print("❌ Report generation failed")

print()
