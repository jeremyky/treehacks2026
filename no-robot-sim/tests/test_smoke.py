"""
Smoke test: StateMachine + PlaceholderActionClient in headless mode (no webcam).
Uses mocked frames and key toggles to run through phases without crashing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root so we can import src
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from src.actions import PlaceholderActionClient, set_manual_confirm, set_artifacts_dir
from src.supervisor import StateMachine, Phase
from src.perception.human_detector import set_human_toggle
from src.perception.debris_detector import set_debris_toggle
from src.perception.injury_detector import set_injury_toggle


def test_smoke_headless():
    """Instantiate ActionClient + StateMachine, run with mock frames through phases. No webcam."""
    set_manual_confirm(False)
    set_artifacts_dir("artifacts_test")
    action_client = PlaceholderActionClient()
    sm = StateMachine(
        action_client,
        phase_timeout_s=300.0,
        callout_interval_s=1.0,
        max_steps=500,
    )
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    import time
    t0 = time.monotonic()

    # Run SEARCH a few ticks (callout may fire)
    for _ in range(5):
        ok = sm.tick(mock_frame, time.monotonic())
        assert ok
        if sm.phase != Phase.SEARCH:
            break

    # Trigger human -> APPROACH
    set_human_toggle(True)
    for _ in range(15):
        ok = sm.tick(mock_frame, time.monotonic())
        assert ok
        if sm.phase == Phase.APPROACH:
            break
    assert sm.phase == Phase.APPROACH

    # Let APPROACH "complete" (navigate_to done, then transition to DEBRIS)
    for _ in range(10):
        ok = sm.tick(mock_frame, time.monotonic())
        assert ok
        if sm.phase == Phase.DEBRIS_ASSESS:
            break
    assert sm.phase == Phase.DEBRIS_ASSESS

    # DEBRIS -> INJURY (optional: set_debris_toggle(True))
    for _ in range(10):
        ok = sm.tick(mock_frame, time.monotonic())
        assert ok
        if sm.phase == Phase.INJURY_SCAN:
            break
    assert sm.phase == Phase.INJURY_SCAN

    # INJURY -> REPORT
    for _ in range(10):
        ok = sm.tick(mock_frame, time.monotonic())
        assert ok
        if sm.phase == Phase.REPORT:
            break
    assert sm.phase == Phase.REPORT

    # REPORT -> DONE (one tick runs send_report and transitions to DONE, so ok may be False)
    ok = sm.tick(mock_frame, time.monotonic())
    assert sm.phase == Phase.DONE
    assert not ok  # tick returns False when DONE

    # Every action must have returned success (no exception)
    assert action_client.send_report(sm.build_report(time.monotonic()), "test").success


def test_force_next_phase():
    """Force next phase with 'n' equivalent."""
    set_manual_confirm(False)
    set_artifacts_dir("artifacts_test")
    sm = StateMachine(PlaceholderActionClient(), phase_timeout_s=60.0, callout_interval_s=10.0, max_steps=100)
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    import time
    t = time.monotonic()
    assert sm.phase == Phase.SEARCH
    sm.force_next_phase(t)
    assert sm.phase == Phase.APPROACH
    sm.force_next_phase(t)
    assert sm.phase == Phase.DEBRIS_ASSESS
    sm.force_next_phase(t)
    assert sm.phase == Phase.INJURY_SCAN
    sm.force_next_phase(t)
    assert sm.phase == Phase.REPORT
    sm.force_next_phase(t)
    assert sm.phase == Phase.DONE
