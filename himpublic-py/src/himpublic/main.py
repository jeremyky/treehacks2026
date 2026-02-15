"""Entrypoint for HIM Public orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from himpublic.orchestrator.config import load_config
from himpublic.orchestrator.agent import OrchestratorAgent
from himpublic.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    p = argparse.ArgumentParser(
        description="HIM Public orchestrator - always-on agent (TreeHacks). Runs until Ctrl+C.",
    )
    p.add_argument(
        "--io",
        choices=["local", "robot", "mock"],
        default="local",
        help="IO mode: local (camera+mic), robot (placeholder), mock (MockRobot)",
    )
    p.add_argument(
        "--video",
        choices=["webcam", "file", "robot"],
        default="webcam",
        help="Video source: webcam, file, or robot (placeholder)",
    )
    p.add_argument("--webcam-index", type=int, default=0, help="Webcam device index (default 0)")
    p.add_argument("--video-path", type=str, default="", help="Video file path (required when --video file)")
    p.add_argument(
        "--command-center",
        type=str,
        default="http://127.0.0.1:8000",
        help="Command center base URL (default http://127.0.0.1:8000)",
    )
    p.add_argument(
        "--no-command-center",
        action="store_true",
        help="Disable posting to command center",
    )
    p.add_argument("--yolo-model", type=str, default="yolov8n.pt", help="YOLO model path (default yolov8n.pt)")
    p.add_argument("--det-thresh", "--detection-threshold", type=float, dest="detection_threshold", default=0.5,
                   help="Person detection score threshold (default 0.5)")
    p.add_argument("--ring-seconds", type=float, default=10.0, help="Ring buffer window in seconds (default 10)")
    p.add_argument("--ring-fps", type=float, default=2.0, help="Ring buffer sample rate FPS (default 2)")
    p.add_argument("--telemetry-hz", type=float, default=1.0, help="Telemetry post rate Hz (default 1)")
    p.add_argument("--llm-hz", type=float, default=1.0, help="LLM policy rate Hz (default 1)")
    p.add_argument("--save-heartbeat-seconds", type=float, default=30.0,
                   help="Heartbeat snapshot interval in seconds (default 30)")
    p.add_argument("--post-interval-frames", type=int, default=30, help="Legacy: post every N frames")
    p.add_argument("--start-phase", type=str, default="",
                   help="Start in this phase (skip boot). e.g. search_localize, approach_confirm. Empty = run boot then search_localize")
    p.add_argument("--show", action="store_true", default=True, help="Show live camera preview with phase/detection overlay (default)")
    p.add_argument("--no-show", action="store_false", dest="show", help="No preview window (e.g. headless or file-only)")
    p.add_argument("--no-tts", action="store_false", dest="tts", default=True,
                   help="Disable TTS (print only). By default TTS is on when pyttsx3 is available.")
    p.add_argument("--no-mic", action="store_false", dest="mic", default=True,
                   help="Disable microphone; use keyboard (type + Enter) for responses. By default mic is on when SpeechRecognition is available.")
    p.add_argument("--log-level", type=str, default="INFO", help="Log level")
    p.add_argument("--debug-decisions", action="store_true",
                   help="Print each decision to terminal: camera (persons, conf) + what was heard -> action, say, listen")
    p.add_argument("--robot-bridge-url", type=str, default="http://192.168.10.102:9090",
                   help="Robot Bridge server URL (for --io robot). Default: http://192.168.10.102:9090")
    p.add_argument("--search-target", choices=["person", "rubble"], default="rubble",
                   help="What to search for: 'person' (COCO person class) or 'rubble' (any object). Default: rubble")
    return p.parse_args()


def main() -> int:
    """Run orchestrator. Returns 0 on success. Ctrl+C for clean shutdown."""
    args = parse_args()

    if args.io == "local" and args.video == "file" and not args.video_path:
        print("Error: --video-path required when --video file")
        return 1

    config = load_config(
        io_mode=args.io,
        video_mode=args.video,
        webcam_index=args.webcam_index,
        video_path=args.video_path or None,
        command_center_url=args.command_center,
        no_command_center=args.no_command_center,
        yolo_model=args.yolo_model,
        detection_threshold=args.detection_threshold,
        post_interval_frames=args.post_interval_frames,
        ring_seconds=args.ring_seconds,
        ring_fps=args.ring_fps,
        telemetry_hz=args.telemetry_hz,
        llm_hz=args.llm_hz,
        save_heartbeat_seconds=args.save_heartbeat_seconds,
        start_phase=args.start_phase or None,
        show_preview=args.show,
        use_tts=args.tts,
        use_mic=args.mic,
        log_level=args.log_level,
        debug_decisions=getattr(args, "debug_decisions", False),
        robot_bridge_url=getattr(args, "robot_bridge_url", None),
        search_target=getattr(args, "search_target", "rubble"),
    )
    setup_logging(config.log_level)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    agent = OrchestratorAgent(config)

    def shutdown() -> None:
        agent.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass  # Windows

    try:
        loop.run_until_complete(agent.run())
    except KeyboardInterrupt:
        agent.request_stop()
        loop.run_until_complete(agent._shutdown())
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
