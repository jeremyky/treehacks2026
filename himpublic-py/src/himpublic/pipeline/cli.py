"""
CLI entry point for the strict rescue pipeline.

Usage:
    python -m himpublic.pipeline.cli --mode demo --explain
    python -m himpublic.pipeline.cli --mode demo --run_id test001
    python -m himpublic.pipeline.cli --mode demo --force_phase TRIAGE_DIALOG_SCAN
"""

from __future__ import annotations

import argparse
import logging
import sys

from .engine import PipelineRunner
from .phases import PIPELINE_PHASES, PipelinePhase


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="HIM Public — strict sequential rescue pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phase order (enforced):
  DEPLOY → SEARCH_HAIL → APPROACH_CONFIRM → DEBRIS_CLEAR →
  TRIAGE_DIALOG_SCAN → REPORT_SEND → MONITOR_WAIT

Examples:
  # Run full pipeline in demo mode
  python -m himpublic.pipeline.cli --mode demo

  # Explain how ordering is enforced
  python -m himpublic.pipeline.cli --explain

  # Skip to a specific phase (debugging only)
  python -m himpublic.pipeline.cli --mode demo --force_phase TRIAGE_DIALOG_SCAN
""",
    )
    p.add_argument(
        "--mode",
        choices=["demo", "robot"],
        default="demo",
        help="Execution mode: demo (simulated) or robot (real hardware). Default: demo",
    )
    p.add_argument(
        "--run_id",
        type=str,
        default="",
        help="Mission run ID. If empty, auto-generated with timestamp.",
    )
    p.add_argument(
        "--out",
        type=str,
        default="missions",
        help="Output directory for mission artifacts. Default: missions/",
    )
    p.add_argument(
        "--force_phase",
        type=str,
        default="",
        choices=["", PipelinePhase.DEPLOY, PipelinePhase.SEARCH_HAIL,
                 PipelinePhase.APPROACH_CONFIRM, PipelinePhase.DEBRIS_CLEAR,
                 PipelinePhase.TRIAGE_DIALOG_SCAN, PipelinePhase.REPORT_SEND,
                 PipelinePhase.MONITOR_WAIT],
        help="Skip to this phase (debugging only). All prior phases are marked SKIPPED.",
    )
    p.add_argument(
        "--explain",
        action="store_true",
        help="Print a human-readable explanation of how pipeline ordering is enforced, then exit.",
    )
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level. Default: INFO",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    runner = PipelineRunner(
        phases=PIPELINE_PHASES,
        mode=args.mode,
        run_id=args.run_id or None,
        output_dir=args.out,
        force_phase=args.force_phase or None,
    )

    # --explain: print explanation and exit
    if args.explain:
        print(runner.explain())
        return 0

    # Run the pipeline
    ctx = runner.run()

    # Print deliverables
    print()
    print("=" * 60)
    print("DELIVERABLES")
    print("=" * 60)
    print()
    print(f"1) Run command:")
    print(f"   python -m himpublic.pipeline.cli --mode demo --run_id {ctx.run_id}")
    print()
    print(f"2) Mission artifacts: {runner.mission_dir}/")
    print()

    # Print output tree
    import os
    print(f"3) Output tree:")
    for root, dirs, files in os.walk(runner.mission_dir):
        level = root.replace(str(runner.mission_dir), "").count(os.sep)
        indent = "   " + "  " * level
        print(f"{indent}{os.path.basename(root)}/")
        sub_indent = "   " + "  " * (level + 1)
        for file in sorted(files):
            size = os.path.getsize(os.path.join(root, file))
            print(f"{sub_indent}{file}  ({size} bytes)")
    print()

    print(f"4) Completed phases: {' → '.join(ctx.completed_phases)}")
    print()

    if ctx.report_path:
        print(f"5) Report: {ctx.report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
