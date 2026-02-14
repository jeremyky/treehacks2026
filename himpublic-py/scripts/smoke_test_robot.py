#!/usr/bin/env python3
"""Smoke test for robot I/O. Validates connectivity layer before CV/autonomy."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smoke_test_robot")


def main() -> int:
    """Run smoke test: TTS, velocity, stop. SDK not implemented yet - expect NotImplementedError."""
    placeholder_ip = "192.168.1.100"
    logger.info("Step 1: Instantiating BoosterAdapter (robot_ip=%s)", placeholder_ip)
    try:
        # Ensure src is on path for himpublic imports
        repo_root = Path(__file__).resolve().parent.parent
        src = repo_root / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))

        from himpublic.io.booster_adapter import BoosterAdapter

        adapter = BoosterAdapter(
            robot_ip=placeholder_ip,
            username="admin",
        )
        logger.info("Step 2: BoosterAdapter instantiated")
    except Exception as e:
        logger.error("Step 2 failed: %s", e)
        return 1

    logger.info("Step 3: Calling play_tts('TreeHacks robot online')")
    try:
        adapter.play_tts("TreeHacks robot online")
        logger.info("Step 3: play_tts completed")
    except NotImplementedError as e:
        logger.warning("Step 3: Expected - SDK not wired yet: %s", e)

    logger.info("Step 4: Calling set_velocity(0.0, 0.5)")
    try:
        adapter.set_velocity(0.0, 0.5)
        logger.info("Step 4: set_velocity completed")
    except NotImplementedError as e:
        logger.warning("Step 4: Expected - SDK not wired yet: %s", e)

    logger.info("Step 5: Sleeping 2 seconds")
    time.sleep(2)

    logger.info("Step 6: Calling stop()")
    try:
        adapter.stop()
        logger.info("Step 6: stop completed")
    except NotImplementedError as e:
        logger.warning("Step 6: Expected - SDK not wired yet: %s", e)

    logger.info("Smoke test finished. SDK methods unimplemented - hardware validation pending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
