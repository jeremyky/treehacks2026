"""Planner schema: WorldState, action space, phase→allowed tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── WorldState ───────────────────────────────────────────────────────────────


@dataclass
class VisionPerson:
    """Single person/person-like detection."""

    bbox: tuple[float, float, float, float]
    conf: float
    depth_m: float | None = None
    center_offset: float = 0.0


@dataclass
class VisionRubble:
    """Single rubble/debris detection."""

    label: str
    bbox: tuple[float, float, float, float]
    conf: float
    depth_m: float | None = None


@dataclass
class WorldState:
    """Unified snapshot for the LLM planner. JSON-serializable."""

    phase: str
    tick: int
    vision: dict[str, Any]
    audio: dict[str, Any]
    robot: dict[str, Any]
    case_file: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "phase": self.phase,
            "tick": self.tick,
            "vision": self.vision,
            "audio": self.audio,
            "robot": self.robot,
            "case_file": self.case_file,
        }


# ── Action space ─────────────────────────────────────────────────────────────

ALLOWED_TOOLS = frozenset({
    # Navigation / search
    "call_out",
    "listen",
    "rotate",
    "walk_forward",
    "scan_pan",
    "wait",
    # Perception
    "scan_vision",
    "capture_image",
    "analyze_images_vlm",
    # Interaction / debris
    "push_obstacle",
    "approach_person",
    # Medical / documentation
    "ask",
    "update_case",
    "generate_report",
})

# Phase → allowed tools (micro-decisions within phase)
PHASE_ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    "boot": frozenset({"wait", "scan_vision"}),
    "search_localize": frozenset({
        "call_out", "listen", "rotate", "walk_forward", "scan_pan",
        "scan_vision", "wait",
    }),
    "approach_confirm": frozenset({
        "rotate", "walk_forward", "approach_person", "scan_vision", "wait",
    }),
    "scene_safety_triage": frozenset({"scan_vision", "wait"}),
    "debris_assessment": frozenset({
        "scan_vision", "push_obstacle", "capture_image", "wait",
    }),
    "injury_detection": frozenset({
        "scan_vision", "capture_image", "analyze_images_vlm", "wait",
    }),
    "assist_communicate": frozenset({
        "ask", "listen", "capture_image", "update_case", "wait",
    }),
    "scan_capture": frozenset({
        "capture_image", "analyze_images_vlm", "update_case", "wait",
    }),
    "report_send": frozenset({"generate_report", "update_case", "wait"}),
    "handoff_escort": frozenset({"listen", "ask", "wait"}),
    "done": frozenset({"wait"}),
}

# Safe tools when phase mismatch (fallback)
SAFE_TOOLS_ANY_PHASE = frozenset({"wait", "scan_vision", "call_out", "listen"})


# ── Plan output format ───────────────────────────────────────────────────────

@dataclass
class ActionSpec:
    """Single action in a plan."""

    tool: str
    args: dict[str, Any]
    expected_observation: str | None = None


@dataclass
class Plan:
    """LLM planner output."""

    phase: str
    intent: str
    actions: list[ActionSpec]
    rationale: str
    confidence: float


# ── Constraints (for executor validation) ────────────────────────────────────

MAX_ROTATE_DEG_PER_STEP = 45.0
MAX_WALK_M_PER_STEP = 0.5
MAX_LISTEN_SECONDS = 20.0
MAX_QUESTIONS_PER_TICK = 2
MAX_CAPTURE_COUNT = 5


# ── WorldState builder ───────────────────────────────────────────────────────

def build_world_state(
    phase: str,
    observation: Any,
    conversation_state: dict[str, Any],
    tick: int = 0,
    last_action: str | None = None,
    heading_deg: float | None = None,
    heard_voice: bool = False,
    voice_angle_deg: float | None = None,
    voice_conf: float | None = None,
) -> WorldState:
    """
    Build unified WorldState from orchestrator state.

    Collects persons (bbox, conf, depth_m, center_offset), rubble (label, bbox, conf, depth_m),
    audio (heard_voice, voice_angle_deg, voice_conf), robot (heading, last_action, constraints),
    case_file (triage state), and tick.
    """
    persons: list[dict] = []
    rubble: list[dict] = []
    primary_offset = 0.0
    if observation is not None and hasattr(observation, "primary_person_center_offset"):
        primary_offset = float(observation.primary_person_center_offset)
    if observation is not None and hasattr(observation, "persons"):
        for i, d in enumerate(observation.persons or []):
            bbox = getattr(d, "bbox", (0, 0, 0, 0))
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                bbox = tuple(float(x) for x in bbox[:4])
            else:
                bbox = (0.0, 0.0, 0.0, 0.0)
            cls_name = getattr(d, "cls_name", "unknown")
            conf = getattr(d, "score", 0.0)
            depth_m = getattr(d, "depth_m", None)
            if cls_name == "person" or "person" in (cls_name or "").lower():
                offset = primary_offset if i == 0 else 0.0
                persons.append({
                    "bbox": bbox,
                    "conf": float(conf),
                    "depth_m": float(depth_m) if depth_m is not None else None,
                    "center_offset": offset,
                })
            else:
                rubble.append({
                    "label": str(cls_name),
                    "bbox": bbox,
                    "conf": float(conf),
                    "depth_m": float(depth_m) if depth_m is not None else None,
                })

    vision = {
        "persons": persons,
        "rubble": rubble,
    }

    audio = {
        "heard_voice": heard_voice,
        "voice_angle_deg": voice_angle_deg,
        "voice_conf": voice_conf,
    }

    robot = {
        "heading_deg": heading_deg,
        "last_action": last_action,
        "constraints": {
            "max_rotate_deg": MAX_ROTATE_DEG_PER_STEP,
            "max_walk_m": MAX_WALK_M_PER_STEP,
            "max_listen_s": MAX_LISTEN_SECONDS,
        },
    }

    triage = conversation_state.get("triage_answers") or {}
    case_file = dict(triage)
    if "images_captured" in conversation_state:
        case_file["images_captured"] = list(conversation_state["images_captured"])

    return WorldState(
        phase=phase,
        tick=tick,
        vision=vision,
        audio=audio,
        robot=robot,
        case_file=case_file,
    )
