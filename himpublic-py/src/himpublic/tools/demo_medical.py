#!/usr/bin/env python3
"""
Medical triage pipeline smoke test — webcam, file, or robot bridge.

Usage:
    # Webcam (default):
    python -m himpublic.tools.demo_medical

    # Single image:
    python -m himpublic.tools.demo_medical --source file --file-path test_frame.png

    # Robot bridge camera:
    python -m himpublic.tools.demo_medical --source robot --robot-url http://192.168.10.102:9090

    # Custom injury prompts:
    python -m himpublic.tools.demo_medical --prompts "blood" "burn" "wound"

Controls:
    r  — generate a triage report from current findings
    q  — quit

Reports are saved to ./reports/
"""

from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Medical triage pipeline demo")
    parser.add_argument("--source", choices=["webcam", "file", "robot"], default="webcam")
    parser.add_argument("--webcam-index", type=int, default=0)
    parser.add_argument("--file-path", type=str, default="")
    parser.add_argument("--robot-url", type=str, default="http://192.168.10.102:9090")
    parser.add_argument("--prompts", nargs="+", default=None,
                        help="Custom injury prompts for open-vocab detector")
    parser.add_argument("--threshold", type=float, default=0.01,
                        help="Detection confidence threshold (default very low to catch weak cues e.g. bleeding knee)")
    parser.add_argument("--no-display", action="store_true", help="Skip OpenCV display window")
    parser.add_argument("--report-dir", type=str, default="reports",
                        help="Directory for triage reports")
    parser.add_argument("--evidence-dir", type=str, default="reports/evidence",
                        help="Directory for evidence images")
    parser.add_argument("--no-pose", action="store_true", help="Disable MediaPipe Pose")
    parser.add_argument("--victim-response", type=str, default="",
                        help="Victim's spoken statement (e.g. 'my arm is bleeding, I think I broke my elbow'). Sets body region and appears in report.")
    args = parser.parse_args()

    import cv2
    import numpy as np

    # ── Initialize subsystems ──
    print("=" * 60)
    print("  Medical Triage Pipeline — Demo")
    print("=" * 60)

    print("\n[1/4] Loading MedicalAssessor...")
    from himpublic.medical.medical_assessor import MedicalAssessor
    assessor = MedicalAssessor(
        prompts=args.prompts,
        confidence_threshold=args.threshold,
        use_pose=not args.no_pose,
    )

    print("[2/4] Initialising EvidenceCollector...")
    from himpublic.medical.evidence_collector import EvidenceCollector
    collector = EvidenceCollector(output_dir=args.evidence_dir)

    print("[3/4] Initialising QuestionPlanner...")
    from himpublic.medical.question_planner import QuestionPlanner
    planner = QuestionPlanner()

    print("[4/4] Initialising ReportBuilder...")
    from himpublic.medical.report_builder import ReportBuilder
    builder = ReportBuilder(output_dir=args.report_dir)

    # ── Frame source ──
    cap = None
    single_frame = None
    robot_client = None

    if args.source == "webcam":
        cap = cv2.VideoCapture(args.webcam_index)
        if not cap.isOpened():
            print(f"ERROR: Cannot open webcam {args.webcam_index}")
            return 1
        print(f"\nWebcam {args.webcam_index} opened.")

    elif args.source == "file":
        if not args.file_path:
            print("ERROR: --file-path required for file source")
            return 1
        single_frame = cv2.imread(args.file_path)
        if single_frame is None:
            print(f"ERROR: Cannot read image {args.file_path}")
            return 1
        print(f"\nLoaded image: {args.file_path} ({single_frame.shape[1]}x{single_frame.shape[0]})")

    elif args.source == "robot":
        try:
            from himpublic.io.robot_client import RobotBridgeClient
            robot_client = RobotBridgeClient(args.robot_url)
            print(f"\nRobot bridge: {args.robot_url}")
        except ImportError:
            print("ERROR: RobotBridgeClient not available")
            return 1

    # ── Detection state ──
    from himpublic.medical.schemas import Finding, TriageReport
    all_findings: list[Finding] = []
    frame_count = 0
    detect_count = 0

    _SEVERITY_COLOUR = {
        "high":   (0, 0, 255),
        "medium": (0, 165, 255),
        "low":    (0, 255, 255),
    }

    print("\nRunning... press 'r' to generate report, 'q' to quit.\n")

    while True:
        # ── Get frame ──
        if args.source == "webcam":
            ret, frame = cap.read()  # type: ignore[union-attr]
            if not ret:
                time.sleep(0.05)
                continue
        elif args.source == "file":
            frame = single_frame.copy()  # type: ignore[union-attr]
        elif args.source == "robot":
            frame = robot_client.get_frame_numpy()  # type: ignore[union-attr]
            if frame is None:
                time.sleep(0.5)
                continue

        frame_count += 1
        collector.push_frame(frame)

        # ── Assess ──
        t0 = time.monotonic()
        findings = assessor.assess(frame)
        elapsed_ms = (time.monotonic() - t0) * 1000

        if findings:
            detect_count += 1
            all_findings = findings  # keep latest
            for f in findings:
                print(
                    f"  [{frame_count:4d}] {f.label:30s} "
                    f"conf={f.confidence:.2f} sev={f.severity:6s} "
                    f"region={f.body_region:20s} ({elapsed_ms:.0f}ms)"
                )

            # Show questions
            questions = planner.next_questions(findings, max_questions=3)
            if questions:
                print(f"  Questions ({len(questions)}):")
                for q in questions:
                    print(f"    → [{q.id}] {q.text}")

        elif frame_count % 60 == 0:
            print(f"  [{frame_count:4d}] no findings ({elapsed_ms:.0f}ms)")

        # ── Display ──
        if not args.no_display:
            display = frame.copy()
            for f in findings:
                x1, y1, x2, y2 = f.bbox_xyxy
                colour = _SEVERITY_COLOUR.get(f.severity, (255, 255, 255))
                cv2.rectangle(display, (x1, y1), (x2, y2), colour, 2)
                label = f"{f.label} ({f.confidence:.2f}) {f.body_region}"
                cv2.putText(display, label, (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2)

            status = f"Findings: {detect_count}/{frame_count} | {elapsed_ms:.0f}ms"
            cv2.putText(display, status, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(display, "Press 'r' for report, 'q' to quit", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            cv2.imshow("Medical Triage Demo", display)

            key = cv2.waitKey(1 if args.source != "file" else 0) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("r"):
                _generate_report(all_findings, collector, planner, builder, args.victim_response)

        # Single image: one pass (unless display is open)
        if args.source == "file" and args.no_display:
            _generate_report(all_findings, collector, planner, builder, args.victim_response)
            break

        time.sleep(0.01)

    # ── Cleanup ──
    if cap is not None:
        cap.release()
    if not args.no_display:
        cv2.destroyAllWindows()

    print(f"\nDone. {detect_count}/{frame_count} frames had findings.")
    return 0


def _parse_body_part_from_text(text: str) -> str | None:
    """Pick first mentioned body part from victim statement (e.g. 'my arm', 'broke my elbow')."""
    if not (text or "").strip():
        return None
    t = text.lower()
    # Order by specificity so "elbow" wins over "arm" when both present
    for part in ("elbow", "knee", "ankle", "wrist", "shoulder", "arm", "leg", "hand", "foot", "head", "chest", "back", "neck"):
        if part in t:
            return part
    return None


def _generate_report(
    findings: list,
    collector: object,
    planner: object,
    builder: object,
    victim_response: str = "",
) -> None:
    """Collect evidence and build a triage report. If victim_response is set, use it for body region and in report."""
    from himpublic.medical.schemas import TriageReport

    if not findings:
        print("\n  No findings to report.\n")
        return

    print("\n  Generating report...")

    victim_response = (victim_response or "").strip()
    body_part = _parse_body_part_from_text(victim_response) if victim_response else None
    if body_part:
        for f in findings:
            f.body_region = body_part
        print(f"  Body region from victim statement: {body_part}")

    # Collect evidence (sharpest frame, crops, annotations)
    collector.collect(findings)  # type: ignore[attr-defined]

    victim_answers = dict(planner.get_answers())  # type: ignore[attr-defined]
    if victim_response:
        victim_answers["victim_statement"] = victim_response
        if body_part:
            victim_answers["injury_location"] = body_part

    scene = "Automated triage assessment from live video feed."
    if victim_response:
        scene += " Victim reported: " + (victim_response[:80] + "…" if len(victim_response) > 80 else victim_response)
    report = TriageReport(
        scene_summary=scene,
        victim_answers=victim_answers,
        findings=findings,
        notes=["Report generated from demo script."],
    )

    path = builder.build_report(report)  # type: ignore[attr-defined]
    if path:
        print(f"  Report saved: {path}\n")
    else:
        print("  Report generation failed.\n")


if __name__ == "__main__":
    sys.exit(main())
