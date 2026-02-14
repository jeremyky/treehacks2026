"""State machine phases: SEARCH -> APPROACH -> DEBRIS -> INJURY -> REPORT."""

from __future__ import annotations

from enum import Enum


class Phase(Enum):
    SEARCH = "search"
    APPROACH = "approach"
    DEBRIS_ASSESS = "debris_assess"
    INJURY_SCAN = "injury_scan"
    REPORT = "report"
    DONE = "done"


# Order for "next phase" and timeouts
PHASE_ORDER = [
    Phase.SEARCH,
    Phase.APPROACH,
    Phase.DEBRIS_ASSESS,
    Phase.INJURY_SCAN,
    Phase.REPORT,
    Phase.DONE,
]


def next_phase(phase: Phase) -> Phase | None:
    """Return next phase in sequence, or None if DONE."""
    try:
        i = PHASE_ORDER.index(phase)
        if i + 1 < len(PHASE_ORDER):
            return PHASE_ORDER[i + 1]
    except ValueError:
        pass
    return None
