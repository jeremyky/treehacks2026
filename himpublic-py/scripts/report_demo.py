#!/usr/bin/env python3
"""
Command Center Report demo: Wizard-of-Oz flow.
Builds report from stub/WoZ data, runs medical chatbot (typed answers),
saves report.json + report.md to artifacts, optionally sends to command center.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

# Add project root for imports
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from himpublic.reporting import (
    build_report,
    build_markdown,
    ArtifactStore,
    report_to_dict,
    validate_report,
)
from himpublic.reporting.types import (
    LocationInfo,
    VictimSummary,
    Detection,
    HazardsDebris,
    Hazard,
    DebrisFinding,
    InjuryFinding,
    RecommendedActionPackage,
    RecommendedAction,
)
from himpublic.chatbot import MedicalChatbot
from himpublic.comms.command_center_client import send_incident_report


def _stub_location() -> LocationInfo:
    return LocationInfo(
        frame="local",
        x=1.0,
        y=2.0,
        yaw=0.0,
        floor="1",
        area_label="corridor",
        confidence=0.8,
        approach_path_status="clear",
        nav_notes="Stub WoZ",
    )


def _stub_victim() -> VictimSummary:
    return VictimSummary(
        victim_id="victim-1",
        detection=Detection(confidence=0.9, method=["manual"], bbox=None),
        responsiveness={"conscious": True, "responds_to_voice": True},
        breathing="unknown",
        mobility="unknown",
    )


def _stub_hazards_debris() -> HazardsDebris:
    return HazardsDebris(
        hazards=[Hazard(type="debris", severity="low", confidence=0.7, notes="Stub")],
        debris=[DebrisFinding(type="rubble", movable=True, confidence=0.8, pose=(1.5, 2.0), notes="")],
        recommended_tools=["gripper"],
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Command center report demo (WoZ)")
    p.add_argument("--command-center", default="", help="Command center base URL (e.g. http://localhost:8000)")
    p.add_argument("--artifacts", default="artifacts", help="Artifacts base dir")
    p.add_argument("--robot-id", default="robot-1", help="Robot ID")
    p.add_argument("--no-send", action="store_true", help="Do not send report to command center")
    args = p.parse_args()

    store = ArtifactStore(base_dir=args.artifacts)
    chatbot = MedicalChatbot()

    print("=== Command Center Report Demo (Wizard-of-Oz) ===\n")
    print("Answer a few triage questions (type and press Enter).\n")

    injuries: list[InjuryFinding] = []  # Optional: add stub injuries here
    questions_asked, answers = chatbot.run_interview(
        input_fn=lambda prompt: input(prompt).strip(),
        victim=_stub_victim(),
        injuries=injuries,
    )
    section = chatbot.produce_section(questions_asked=questions_asked, answers=answers, injuries=injuries)

    report = build_report(
        robot_id=args.robot_id,
        location=_stub_location(),
        victim=_stub_victim(),
        hazards_debris=_stub_hazards_debris(),
        injuries=injuries,
        medical_chatbot=section,
        images=[],
        recommended_actions=RecommendedActionPackage(
            recommended_actions=[
                RecommendedAction(action="Stabilize victim", priority="high", why="Triage recommendation"),
            ]
        ),
        comms_status=None,
    )

    errs = validate_report(report)
    if errs:
        print("Validation issues:", errs)

    report_dict = report_to_dict(report)
    endpoint = None if args.no_send else (args.command_center or None)
    comms_status = send_incident_report(report_dict, endpoint_url=endpoint or "")
    report = dataclasses.replace(report, comms_status=comms_status)
    report_dict = report_to_dict(report)

    md = build_markdown(report, image_base_path="images")
    session = store.save_report(report, markdown_content=md)

    print(f"\nReport saved: {session}")
    print(f"  report.json  report.md")
    print(f"  Triage: {section.triage_priority} (confidence {section.overall_confidence:.2f})")
    print(f"  Comms: sent={comms_status.sent} endpoint={comms_status.endpoint or 'N/A'}")


if __name__ == "__main__":
    main()
