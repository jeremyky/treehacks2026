"""Orchestrator module - main loop, state machine, phases."""

from .state_machine import MissionState, MissionEvent
from .config import OrchestratorConfig
from .phases import Phase, PHASE_LABELS, parse_phase

__all__ = ["OrchestratorAgent", "MissionState", "MissionEvent", "OrchestratorConfig", "Phase", "PHASE_LABELS", "parse_phase"]


def __getattr__(name: str):
    """Lazy-load OrchestratorAgent so dialogue_manager can be used without pulling in agent (cv2, etc.)."""
    if name == "OrchestratorAgent":
        from .agent import OrchestratorAgent
        return OrchestratorAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
