#!/usr/bin/env python3
"""Smoke test for open-vocabulary rubble detection.

Usage:
    # Webcam (default):
    python -m himpublic.tools.test_openvocab

    # Webcam with custom index:
    python -m himpublic.tools.test_openvocab --source webcam --webcam-index 1

    # Single image file:
    python -m himpublic.tools.test_openvocab --source file --file-path test_frame.png

    # Robot bridge camera:
    python -m himpublic.tools.test_openvocab --source robot --robot-url http://192.168.10.102:9090

    # Custom prompts:
    python -m himpublic.tools.test_openvocab --prompts "cardboard box" "suitcase" "rubble"

Press 'q' to quit the live preview window.
"""

from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-vocab rubble detection smoke test")
    parser.add_argument("--source", choices=["webcam", "file", "robot"], default="webcam")
    parser.add_argument("--webcam-index", type=int, default=0)
    parser.add_argument("--file-path", type=str, default="")
    parser.add_argument("--robot-url", type=str, default="http://192.168.10.102:9090")
    parser.add_argument("--prompts", nargs="+", default=None,
                        help="Custom text prompts (default: built-in rubble prompts)")
    parser.add_argument("--threshold", type=float, default=0.15,
                        help="Detection confidence threshold (default 0.15)")
    parser.add_argument("--no-display", action="store_true", help="Skip OpenCV display window")
    args = parser.parse_args()

    import cv2
    import numpy as np

    # ── Initialize detector ──
    print("Loading OpenVocabDetector (YOLO-World)...")
    from himpublic.perception.openvocab import OpenVocabDetector
    detector = OpenVocabDetector(
        prompts=args.prompts,
        confidence_threshold=args.threshold,
    )
    print(f"  Prompts: {detector.prompts}")
    print(f"  Threshold: {args.threshold}")

    # ── Initialize frame source ──
    cap = None
    single_frame = None

    if args.source == "webcam":
        cap = cv2.VideoCapture(args.webcam_index)
        if not cap.isOpened():
            print(f"ERROR: Cannot open webcam {args.webcam_index}")
            return 1
        print(f"Webcam {args.webcam_index} opened.")

    elif args.source == "file":
        if not args.file_path:
            print("ERROR: --file-path required for file source")
            return 1
        single_frame = cv2.imread(args.file_path)
        if single_frame is None:
            print(f"ERROR: Cannot read image {args.file_path}")
            return 1
        print(f"Loaded image: {args.file_path} ({single_frame.shape[1]}x{single_frame.shape[0]})")

    elif args.source == "robot":
        from himpublic.io.robot_client import RobotBridgeClient
        client = RobotBridgeClient(args.robot_url)
        print(f"Robot bridge: {args.robot_url}")

    # ── Detection loop ──
    print("\nRunning detection... (press 'q' to quit)\n")
    frame_count = 0
    detect_count = 0

    while True:
        # Get frame
        if args.source == "webcam":
            ret, frame = cap.read()
            if not ret:
                print("Webcam: no frame")
                time.sleep(0.1)
                continue
        elif args.source == "file":
            frame = single_frame.copy()
        elif args.source == "robot":
            frame = client.get_frame_numpy()
            if frame is None:
                print("Robot: no frame")
                time.sleep(0.5)
                continue

        frame_count += 1
        t0 = time.monotonic()

        # Detect
        all_dets = detector.detect_all(frame)
        best = detector.detect(frame)
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Log
        if best.found:
            detect_count += 1
            print(
                f"[{frame_count:4d}] FOUND: {best.label:20s} score={best.score:.3f} "
                f"bbox=[{best.bbox_xyxy[0]:.0f},{best.bbox_xyxy[1]:.0f},"
                f"{best.bbox_xyxy[2]:.0f},{best.bbox_xyxy[3]:.0f}] "
                f"({elapsed_ms:.0f}ms) [{len(all_dets)} total]"
            )
        elif frame_count % 30 == 0:
            print(f"[{frame_count:4d}] no rubble ({elapsed_ms:.0f}ms)")

        # Draw
        if not args.no_display:
            display = frame.copy()
            for det in all_dets:
                x1, y1, x2, y2 = [int(v) for v in det.bbox_xyxy]
                color = (0, 255, 0) if det.score > 0.3 else (0, 255, 255)
                cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
                label = f"{det.label} {det.score:.2f}"
                cv2.putText(display, label, (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            status = f"Rubble: {detect_count}/{frame_count} | {elapsed_ms:.0f}ms"
            cv2.putText(display, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("OpenVocab Rubble Detection", display)
            key = cv2.waitKey(1 if args.source != "file" else 0) & 0xFF
            if key == ord("q"):
                break

        # Single image: one iteration
        if args.source == "file":
            if args.no_display:
                break
            continue

        time.sleep(0.01)

    # Cleanup
    if cap is not None:
        cap.release()
    if not args.no_display:
        cv2.destroyAllWindows()

    print(f"\nDone. {detect_count}/{frame_count} frames had rubble detections.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
