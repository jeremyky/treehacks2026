#!/usr/bin/env python3
"""
Run the orchestrator with webcam + TTS + microphone for a live triage demo.

The robot will speak triage questions (TTS), listen for your responses (mic or type),
use the webcam for visual assessment, then generate a triage report when done.

Usage:
    python -m himpublic.tools.run_medical_voice_demo

    # Skip boot/search and start directly at triage Q&A:
    python -m himpublic.tools.run_medical_voice_demo
    (script passes --start-phase assist_communicate by default)

    # Optional: disable TTS (print only) or mic (type responses):
    python -m himpublic.main --video webcam --start-phase assist_communicate --no-tts
    python -m himpublic.main --video webcam --start-phase assist_communicate --no-mic

Reports are written to himpublic-py/reports/ (and optionally converted to PDF if available).
Press Ctrl+C to stop.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    # Run from project root so reports/ is always himpublic-py/reports (visible, no chmod needed)
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    reports_dir = project_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(project_root)
    print(f"Working directory: {project_root}", flush=True)
    print(f"Reports will be saved to: {reports_dir.resolve()}", flush=True)

    argv = [
        sys.argv[0],
        "--video", "webcam",
        "--start-phase", "assist_communicate",
        "--debug-decisions",
    ]
    sys.argv = argv + sys.argv[1:]
    from himpublic.main import main as orchestrator_main
    return orchestrator_main()


if __name__ == "__main__":
    sys.exit(main())
