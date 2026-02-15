"""Test harness for LLM Planner-Executor. Run: python -m himpublic.tools.test_planner --scenario <name>."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# Add src to path for running as script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from himpublic.planner import (
    WorldState,
    Plan,
    ActionSpec,
    build_world_state,
    plan_next_actions,
    validate_plan,
    plan_to_decision,
    dispatch_action,
)
from himpublic.planner.schema import PHASE_ALLOWED_TOOLS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def _mock_obs(persons: int = 0, rubble: int = 0, confidence: float = 0.0, offset: float = 0.0):
    """Build mock observation."""
    class MockDetection:
        def __init__(self, cls_name: str, score: float):
            self.cls_name = cls_name
            self.score = score
            self.bbox = (100, 100, 200, 200)
    class MockObs:
        pass
    obs = MockObs()
    obs.timestamp = 0.0
    obs.primary_person_center_offset = offset
    obs.confidence = confidence
    obs.persons = []
    for _ in range(persons):
        obs.persons.append(MockDetection("person", confidence or 0.7))
    for _ in range(rubble):
        obs.persons.append(MockDetection("debris", confidence or 0.6))
    return obs


SCENARIO_WORLD_STATES = {
    "search_no_person": lambda: WorldState(
        phase="search_localize",
        tick=1,
        vision={"persons": [], "rubble": []},
        audio={"heard_voice": False, "voice_angle_deg": None, "voice_conf": None},
        robot={"heading_deg": 0, "last_action": None, "constraints": {}},
        case_file={},
    ),
    "voice_at_30deg": lambda: WorldState(
        phase="search_localize",
        tick=2,
        vision={"persons": [], "rubble": []},
        audio={"heard_voice": True, "voice_angle_deg": 30.0, "voice_conf": 0.8},
        robot={"heading_deg": 0, "last_action": "listen", "constraints": {}},
        case_file={},
    ),
    "person_at_3m": lambda: WorldState(
        phase="approach_confirm",
        tick=3,
        vision={
            "persons": [{"bbox": (200, 100, 400, 400), "conf": 0.85, "depth_m": 3.0, "center_offset": 0.1}],
            "rubble": [],
        },
        audio={"heard_voice": False, "voice_angle_deg": None, "voice_conf": None},
        robot={"heading_deg": 0, "last_action": "walk_forward", "constraints": {}},
        case_file={},
    ),
    "rubble_near_person": lambda: WorldState(
        phase="debris_assessment",
        tick=4,
        vision={
            "persons": [{"bbox": (250, 150, 400, 450), "conf": 0.9, "depth_m": 2.0, "center_offset": 0.0}],
            "rubble": [{"label": "cardboard box", "bbox": (100, 200, 300, 350), "conf": 0.75, "depth_m": 2.5}],
        },
        audio={"heard_voice": False, "voice_angle_deg": None, "voice_conf": None},
        robot={"heading_deg": 0, "last_action": "scan_vision", "constraints": {}},
        case_file={},
    ),
    "victim_bleeding_leg": lambda: WorldState(
        phase="assist_communicate",
        tick=5,
        vision={
            "persons": [{"bbox": (200, 100, 450, 450), "conf": 0.9, "depth_m": 1.5, "center_offset": 0.0}],
            "rubble": [],
        },
        audio={"heard_voice": True, "voice_angle_deg": None, "voice_conf": None},
        robot={"heading_deg": 0, "last_action": "ask", "constraints": {}},
        case_file={"injury_reported": "bleeding left leg"},
    ),
}


SCENARIO_MOCK_PLANS = {
    "search_no_person": Plan(
        phase="search_localize",
        intent="Scan and call out",
        actions=[
            ActionSpec("scan_vision", {"mode": "person+rubble"}),
            ActionSpec("call_out", {"text": "Can you hear me? Is anyone there?"}),
            ActionSpec("listen", {"seconds": 2.0}),
        ],
        rationale="No persons or voice detected; scan then call out and listen.",
        confidence=0.8,
    ),
    "voice_at_30deg": Plan(
        phase="search_localize",
        intent="Turn toward voice and approach",
        actions=[
            ActionSpec("rotate", {"deg": 30.0}),
            ActionSpec("walk_forward", {"meters": 0.3}),
            ActionSpec("listen", {"seconds": 2.0}),
            ActionSpec("scan_vision", {"mode": "person"}),
        ],
        rationale="Voice heard at +30 deg; rotate and walk toward it, then listen and scan.",
        confidence=0.85,
    ),
    "person_at_3m": Plan(
        phase="approach_confirm",
        intent="Approach detected person",
        actions=[
            ActionSpec("approach_person", {"target_id": "person_0"}),
        ],
        rationale="Person detected at 3m; approach.",
        confidence=0.9,
    ),
    "rubble_near_person": Plan(
        phase="debris_assessment",
        intent="Clear rubble then rescan",
        actions=[
            ActionSpec("push_obstacle", {"direction": "forward", "strength": "low"}),
            ActionSpec("scan_vision", {"mode": "person+rubble"}),
        ],
        rationale="Rubble near person; push to clear, then rescan.",
        confidence=0.75,
    ),
    "victim_bleeding_leg": Plan(
        phase="assist_communicate",
        intent="Ask, capture lower body, analyze, report",
        actions=[
            ActionSpec("ask", {"text": "I understand you have a bleeding injury on your left leg. Can you keep pressure on it?"}),
            ActionSpec("capture_image", {"target": "lower_body", "count": 2}),
            ActionSpec("analyze_images_vlm", {"prompt": "Describe visible injuries on lower body"}),
            ActionSpec("update_case", {"fields": {"injury_location": "left leg", "injury_type": "bleeding"}}),
            ActionSpec("generate_report", {}),
        ],
        rationale="Victim reported bleeding left leg; ask, capture, analyze, update case, generate report.",
        confidence=0.85,
    ),
}


def run_scenario(
    scenario: str,
    use_llm: bool = False,
    api_key: str | None = None,
) -> int:
    """Run one scenario. Returns 0 on success."""
    if scenario not in SCENARIO_WORLD_STATES:
        logger.error("Unknown scenario: %s. Valid: %s", scenario, list(SCENARIO_WORLD_STATES))
        return 1

    ws = SCENARIO_WORLD_STATES[scenario]()
    logger.info("[STATE] scenario=%s phase=%s persons=%d rubble=%d",
        scenario, ws.phase, len(ws.vision.get("persons", [])), len(ws.vision.get("rubble", [])))

    if use_llm and api_key:
        plan = plan_next_actions(ws, api_key=api_key)
    else:
        plan = SCENARIO_MOCK_PLANS.get(scenario)
        if not plan:
            logger.error("No mock plan for scenario %s", scenario)
            return 1

    logger.info("[PLANNER] plan phase=%s intent=%s actions=%s",
        plan.phase, plan.intent, [a.tool for a in plan.actions])

    ok, validated, errors = validate_plan(plan, ws.phase)
    if errors:
        logger.warning("[PLANNER] validation errors: %s", errors)
    if not validated and plan.actions:
        logger.error("All actions filtered out")
        return 1

    result = plan_to_decision(plan, validated)
    decision = result["decision"]
    logger.info("[PLANNER] decision: action=%s mode=%s", decision.action, decision.mode)

    ctx = {"robot": None, "audio_io": None, "cc_client": None}
    for i, a in enumerate(validated[:3]):  # Dispatch first 3 for harness
        res = dispatch_action(a, ctx)
        logger.info("[EXEC] %d %s -> ok=%s", i + 1, a.tool, res.get("ok", False))
        if not res.get("ok"):
            logger.warning("Dispatch failed for %s: %s", a.tool, res.get("message"))

    logger.info("Scenario %s completed successfully", scenario)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Test planner-executor harness")
    p.add_argument("--scenario", default="search_no_person",
        choices=list(SCENARIO_WORLD_STATES),
        help="Scenario to run")
    p.add_argument("--use-llm", action="store_true", help="Use real LLM (requires OPENAI_API_KEY)")
    p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"), help="OpenAI API key")
    args = p.parse_args()

    api_key = (args.api_key or "").strip() or None
    if args.use_llm and not api_key:
        logger.error("--use-llm requires OPENAI_API_KEY")
        return 1

    return run_scenario(args.scenario, use_llm=args.use_llm, api_key=api_key)


if __name__ == "__main__":
    sys.exit(main())
