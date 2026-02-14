"""
Wizard-of-Oz main entrypoint.
Continuously read camera (+ optional mic), run perception placeholders, transition phases.
Keys: h=human, d=debris, i=injury, n=next phase, q=quit.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure we can import from src
if __name__ == "__main__" and "__file__" in dir():
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import cv2
import numpy as np

from src.config import Config
from src.actions import PlaceholderActionClient, set_manual_confirm, set_artifacts_dir
from src.supervisor import StateMachine, Phase
from src.perception.human_detector import set_human_toggle, get_human_toggle
from src.perception.debris_detector import set_debris_toggle, get_debris_toggle
from src.perception.injury_detector import set_injury_toggle, get_injury_toggle


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wizard-of-Oz pipeline: camera + placeholders, phase state machine.")
    p.add_argument("--manual", action="store_true", help="Wait for Enter after each action (simulate completion)")
    p.add_argument("--typed-mic", action="store_true", help="Use typed input for mic (future: transcript)")
    p.add_argument("--show", action="store_true", default=True, help="Show webcam window (default True)")
    p.add_argument("--no-show", action="store_false", dest="show", help="Headless (no window)")
    p.add_argument("--save-video", action="store_true", help="Save frames to video file")
    p.add_argument("--save-video-path", type=str, default="artifacts/video.avi", help="Output video path")
    p.add_argument("--max-steps", type=int, default=0, help="Max ticks (0 = no limit)")
    return p.parse_args()


def draw_overlay(
    frame: np.ndarray,
    phase: str,
    last_action: str,
    last_reason: str,
    h: bool,
    d: bool,
    i: bool,
) -> np.ndarray:
    """Overlay phase, last action, toggles on frame."""
    out = frame.copy()
    y = 30
    line_h = 28
    cv2.putText(out, f"Phase: {phase}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    y += line_h
    cv2.putText(out, f"Last: {last_action} ({last_reason})", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    y += line_h
    cv2.putText(out, f"[h] human={h} [d] debris={d} [i] injury={i}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 0), 1)
    y += line_h
    cv2.putText(out, "[n] next phase  [q] quit", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return out


def main() -> int:
    args = parse_args()
    config = Config.from_args(args)

    # Artifacts
    Path(config.artifacts_dir).mkdir(parents=True, exist_ok=True)
    Path(config.reports_dir).mkdir(parents=True, exist_ok=True)
    set_artifacts_dir(config.artifacts_dir)
    set_manual_confirm(config.manual_confirm_actions)

    # Action client (placeholder)
    action_client = PlaceholderActionClient()

    # State machine
    sm = StateMachine(
        action_client,
        phase_timeout_s=config.phase_timeout_s,
        callout_interval_s=config.callout_interval_s,
        max_steps=config.max_steps,
    )

    # Camera: only open when showing window (avoids open on headless/CI)
    cap = None
    camera_available = False
    if config.show:
        cap = cv2.VideoCapture(0)
        camera_available = cap.isOpened()
        if not camera_available:
            print("WARNING: Could not open webcam. Running headless with dummy frame.", file=sys.stderr)
            cap.release()
            cap = None
            config.show = False

    writer = None
    if config.save_video:
        Path(config.artifacts_dir).mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        w, h = 640, 480
        if cap is not None:
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(config.save_video_path, fourcc, config.loop_hz, (w, h))

    dt = 1.0 / config.loop_hz
    report_snapshot_saved = False
    try:
        while True:
            t0 = time.monotonic()
            if cap is not None and camera_available:
                ret, frame = cap.read()
                if not ret or frame is None:
                    if not config.show:
                        frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    else:
                        break
            else:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)

            # Key handling (non-blocking via opencv waitKey(1))
            key = cv2.waitKey(1) & 0xFF if config.show else 0xFF
            if key == ord("q"):
                print("Quit (q)")
                break
            if key == ord("h"):
                set_human_toggle(not get_human_toggle())
            if key == ord("d"):
                set_debris_toggle(not get_debris_toggle())
            if key == ord("i"):
                set_injury_toggle(not get_injury_toggle())
            if key == ord("n"):
                sm.force_next_phase(time.monotonic())

            # Save one snapshot when entering REPORT (for report JSON)
            if sm.phase == Phase.REPORT and not report_snapshot_saved:
                Path(config.reports_dir).mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(Path(config.reports_dir) / "snapshot.jpg"), frame)
                report_snapshot_saved = True

            # One tick
            ok = sm.tick(frame, time.monotonic())
            if not ok:
                print("State machine done.")
                break

            # Overlay and show
            disp = draw_overlay(
                frame,
                sm.phase.value,
                sm.ctx.last_action_name,
                sm.ctx.last_action_reason,
                get_human_toggle(),
                get_debris_toggle(),
                get_injury_toggle(),
            )
            if config.show:
                cv2.imshow("Wizard-of-Oz", disp)
            if writer is not None:
                writer.write(disp)

            elapsed = time.monotonic() - t0
            if elapsed < dt:
                time.sleep(dt - elapsed)
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.release()
        if config.show:
            cv2.destroyAllWindows()

    print("Exiting. Logs: artifacts/action_calls.jsonl, reports: artifacts/reports/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
