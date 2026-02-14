#!/usr/bin/env python3
"""
Sample: generate a medical report from mocked observations and 2–3 sample image paths.
Run from repo root: python scripts/generate_medical_report_sample.py [--out-dir ARTIFACTS_DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from himpublic.reporting.render_medical_report import generate_medical_report


def main() -> None:
    p = argparse.ArgumentParser(description="Generate sample medical report from mocked data")
    p.add_argument("--out-dir", default="artifacts", help="Base dir for sessions (default: artifacts)")
    p.add_argument("--session-id", default="sample_session_001", help="Session ID for output paths")
    args = p.parse_args()

    session_ctx = {
        "session_id": args.session_id,
        "report_id": "report_sample_001",
        "timestamp_start": 1707890123.0,
        "timestamp_end": 1707890423.0,
        "timezone": "UTC",
        "robot_id": "robot-1",
        "operator_id": "op-1",
        "environment_label": "Building A, Floor 2, Room 204",
    }

    observations = {
        "location_estimate": "Corridor near stairwell B, east wing",
        "coordinates": "x=12.4, y=8.2",
        "location_derivation": "Visual landmarks (exit sign); last known waypoint",
        "access_constraints": ["Debris near door; narrow passage"],
        "suggested_approach_route": "Enter from east corridor, turn left at exit sign; avoid rubble pile on right.",
        "one_liner": "One adult, seated, responsive to voice; possible bleeding left forearm.",
        "estimated_age_range": "adult",
        "estimated_sex": "unknown",
        "consciousness": "responsive to voice",
        "primary_concern": "possible bleeding from left forearm; limited mobility",
        "triage_category": "Delayed",
        "overall_confidence": 0.72,
        "confidence_explanation": "Clear verbal response; visual cue consistent with forearm injury.",
        "abcde": {
            "airway": {"status": "patent", "evidence_ids": ["E1"], "confidence": 0.9, "notes": "speech clear"},
            "breathing": {"status": "adequate", "evidence_ids": ["E1"], "confidence": 0.85, "notes": "no distress"},
            "circulation": {"status": "possible bleeding", "evidence_ids": ["E2", "E3"], "confidence": 0.7, "notes": "forearm"},
            "disability": {"status": "alert", "evidence_ids": ["E1"], "confidence": 0.9, "notes": ""},
            "exposure": {"status": "partial", "evidence_ids": ["E2"], "confidence": 0.6, "notes": "left arm visible"},
        },
        "suspected_injuries": [
            {
                "injury_type": "laceration",
                "body_location": "left forearm",
                "severity_estimate": "moderate",
                "confidence": 0.7,
                "rationale": "Visible wound and blood on sleeve; person reported 'my arm is bleeding'.",
                "immediate_actions_recommended": ["Apply pressure with clean dressing", "Consider elevation"],
                "evidence_ids": ["E2", "E3", "E4"],
            },
        ],
        "hazards_nearby": [
            {"description": "Unstable debris near doorway", "risk_level": "medium", "evidence_ids": ["E1"]},
        ],
        "uncertainties": [
            {"item": "Severity of bleeding", "reason": "No direct wound inspection", "alternative_hypotheses": ["superficial vs arterial"]},
            {"item": "Fracture vs soft tissue", "reason": "Limited mobility could be either", "alternative_hypotheses": ["fracture", "sprain", "pain only"]},
        ],
        "recommended_actions": [
            {"action": "Dispatch medic to location; bring tourniquet and pressure dressing", "urgency": "high", "safety_warning": False},
            {"action": "Stabilize debris before entry if possible", "urgency": "medium", "safety_warning": True},
            {"action": "Prioritize evacuation once stable", "urgency": "high", "safety_warning": False},
        ],
    }

    # Mock image paths (relative to session images/ dir; may not exist)
    images = [
        {"file_path": "scene_overview_001.jpg", "section": "scene_overview", "caption": "Wide view of corridor and victim location"},
        {"file_path": "scene_overview_002.jpg", "section": "scene_overview", "caption": "Approach view"},
        {"file_path": "injury_forearm_001.jpg", "section": "injury_closeup", "caption": "Left forearm possible laceration"},
    ]

    audio = [
        {"transcript_snippet": "My arm is bleeding. I can't move it much.", "timestamp": 1707890200.0, "confidence": 0.92},
    ]

    artifact_paths = {
        "sessions_base": str(Path(args.out_dir) / "sessions"),
        "images_relative": "images",
    }

    report_md_path, pdf_path = generate_medical_report(
        session_ctx=session_ctx,
        observations=observations,
        images=images,
        audio=audio,
        model_outputs=None,
        artifact_paths=artifact_paths,
    )

    print(f"Report written: {report_md_path}")
    print(f"PDF (optional): {pdf_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
