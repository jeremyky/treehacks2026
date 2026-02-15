"""Executor: validate plan, dispatch actions via existing orchestrator primitives."""

from __future__ import annotations

import logging
from typing import Any, Callable

from .schema import (
    Plan,
    ActionSpec,
    PHASE_ALLOWED_TOOLS,
    SAFE_TOOLS_ANY_PHASE,
    MAX_ROTATE_DEG_PER_STEP,
    MAX_WALK_M_PER_STEP,
    MAX_LISTEN_SECONDS,
    MAX_QUESTIONS_PER_TICK,
    MAX_CAPTURE_COUNT,
)

logger = logging.getLogger(__name__)


def validate_plan(
    plan: Plan,
    current_phase: str,
    phase_mismatch_allows_safe_only: bool = True,
) -> tuple[bool, list[ActionSpec], list[str]]:
    """
    Validate plan against constraints. Returns (ok, validated_actions, errors).
    - Clamps rotate/walk/listen to bounds
    - Filters actions by phase-allowed tools
    - Caps questions per tick
    """
    errors: list[str] = []
    validated: list[ActionSpec] = []
    allowed = PHASE_ALLOWED_TOOLS.get(current_phase, SAFE_TOOLS_ANY_PHASE)
    phase_ok = plan.phase == current_phase
    if phase_mismatch_allows_safe_only and not phase_ok:
        allowed = SAFE_TOOLS_ANY_PHASE
        errors.append(f"Phase mismatch ({plan.phase} vs {current_phase}); only safe tools allowed")

    question_count = 0
    for a in plan.actions:
        if a.tool not in allowed:
            errors.append(f"Tool {a.tool!r} not allowed in phase {current_phase}")
            continue
        args = dict(a.args)

        # Clamp numeric bounds
        if a.tool == "rotate":
            deg = args.get("deg", 0)
            try:
                deg = float(deg)
                deg = max(-MAX_ROTATE_DEG_PER_STEP, min(MAX_ROTATE_DEG_PER_STEP, deg))
                args["deg"] = deg
            except (TypeError, ValueError):
                args["deg"] = 0.0
        elif a.tool == "walk_forward":
            m = args.get("meters", 0)
            try:
                m = float(m)
                m = max(0, min(MAX_WALK_M_PER_STEP, m))
                args["meters"] = m
            except (TypeError, ValueError):
                args["meters"] = 0.0
        elif a.tool == "listen":
            s = args.get("seconds", 2.0)
            try:
                s = float(s)
                s = max(0.5, min(MAX_LISTEN_SECONDS, s))
                args["seconds"] = s
            except (TypeError, ValueError):
                args["seconds"] = 2.0
        elif a.tool == "wait":
            s = args.get("seconds", 1.0)
            try:
                s = float(s)
                s = max(0.1, min(30.0, s))
                args["seconds"] = s
            except (TypeError, ValueError):
                args["seconds"] = 1.0
        elif a.tool == "ask":
            question_count += 1
            if question_count > MAX_QUESTIONS_PER_TICK:
                errors.append(f"Exceeded max questions per tick ({MAX_QUESTIONS_PER_TICK})")
                continue
        elif a.tool == "capture_image":
            count = args.get("count", 1)
            try:
                count = int(count)
                count = max(1, min(MAX_CAPTURE_COUNT, count))
                args["count"] = count
            except (TypeError, ValueError):
                args["count"] = 1

        validated.append(ActionSpec(tool=a.tool, args=args, expected_observation=a.expected_observation))

    ok = len(validated) > 0
    if not validated and plan.actions:
        errors.append("All actions were filtered out")
    return ok, validated if validated else [], errors


def dispatch_action(
    action: ActionSpec,
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    Dispatch single action. Returns result dict with 'ok', 'message', optional 'data'.
    Uses context to access robot, audio_io, placeholders, etc.
    """
    robot = context.get("robot")
    audio_io = context.get("audio_io")
    cc_client = context.get("cc_client")

    try:
        if action.tool == "call_out":
            text = action.args.get("text", "")
            if audio_io:
                audio_io.speak(text)
            if cc_client and getattr(cc_client, "_enabled", False):
                cc_client.post_event({"event": "robot_said", "text": text})
            logger.info("[EXEC] call_out: %s", text[:50])
            return {"ok": True, "message": "call_out done"}

        if action.tool == "listen":
            seconds = action.args.get("seconds", 2.0)
            transcript = ""
            if audio_io and hasattr(audio_io, "listen"):
                transcript = (audio_io.listen(seconds) or "").strip()
            logger.info("[EXEC] listen(%.1fs): heard=%r", seconds, transcript[:50] if transcript else "—")
            return {"ok": True, "message": "listen done", "data": {"transcript": transcript}}

        if action.tool == "rotate":
            deg = action.args.get("deg", 0)
            if robot and hasattr(robot, "set_velocity"):
                # Simple rotate: positive = left, negative = right
                omega = 0.3 if deg > 0 else -0.3
                robot.set_velocity(0.0, omega)
                # Placeholder: real impl would turn for time based on deg
            logger.info("[EXEC] rotate(%.1f deg)", deg)
            return {"ok": True, "message": "rotate command sent"}

        if action.tool == "walk_forward":
            meters = action.args.get("meters", 0.2)
            if robot and hasattr(robot, "set_velocity"):
                robot.set_velocity(0.2, 0.0)
            logger.info("[EXEC] walk_forward(%.2f m)", meters)
            return {"ok": True, "message": "walk_forward command sent"}

        if action.tool == "wait":
            import time
            seconds = action.args.get("seconds", 1.0)
            time.sleep(min(seconds, 2.0))  # Cap sleep in executor to avoid long blocks
            logger.info("[EXEC] wait(%.1fs)", seconds)
            return {"ok": True, "message": "wait done"}

        if action.tool == "scan_vision":
            logger.info("[EXEC] scan_vision(mode=%s)", action.args.get("mode", "person"))
            return {"ok": True, "message": "scan_vision (perception loop handles)"}

        if action.tool == "capture_image":
            target = action.args.get("target", "full_body")
            count = action.args.get("count", 1)
            try:
                from himpublic.orchestrator.placeholders import capture_image
                ids = []
                for _ in range(count):
                    ids.append(capture_image(target))
                logger.info("[EXEC] capture_image(target=%s count=%d) -> %s", target, count, ids)
                return {"ok": True, "message": "captured", "data": {"ids": ids}}
            except Exception as e:
                logger.warning("[EXEC] capture_image failed: %s", e)
                return {"ok": False, "message": str(e)}

        if action.tool == "push_obstacle":
            direction = action.args.get("direction", "forward")
            strength = action.args.get("strength", "low")
            logger.info("[EXEC] push_obstacle(direction=%s strength=%s) [placeholder]", direction, strength)
            return {"ok": True, "message": "push_obstacle placeholder"}

        if action.tool == "approach_person":
            target_id = action.args.get("target_id") or action.args.get("target", "")
            logger.info("[EXEC] approach_person(target_id=%s) [placeholder]", target_id)
            return {"ok": True, "message": "approach_person placeholder"}

        if action.tool == "ask":
            text = action.args.get("text", "")
            if audio_io:
                audio_io.speak(text)
            if cc_client and getattr(cc_client, "_enabled", False):
                cc_client.post_event({"event": "robot_said", "text": text})
            logger.info("[EXEC] ask: %s", text[:50])
            return {"ok": True, "message": "ask spoken"}

        if action.tool == "update_case":
            fields = action.args.get("fields", {})
            logger.info("[EXEC] update_case: %s", list(fields.keys()))
            return {"ok": True, "message": "update_case", "data": {"fields": fields}}

        if action.tool == "generate_report":
            logger.info("[EXEC] generate_report [triggers report flow]")
            return {"ok": True, "message": "generate_report placeholder"}

        if action.tool == "analyze_images_vlm":
            prompt = action.args.get("prompt", "")
            logger.info("[EXEC] analyze_images_vlm: %s [placeholder]", prompt[:40])
            return {"ok": True, "message": "analyze_images_vlm placeholder"}

        if action.tool == "scan_pan":
            logger.info("[EXEC] scan_pan [placeholder]")
            return {"ok": True, "message": "scan_pan placeholder"}

    except Exception as e:
        logger.warning("[EXEC] dispatch_action(%s) failed: %s", action.tool, e)
        return {"ok": False, "message": str(e)}

    return {"ok": False, "message": f"Unknown tool: {action.tool}"}


# Tools that need explicit dispatch (not handled by actuation loop via Decision)
DISPATCH_ONLY_TOOLS = frozenset({
    "push_obstacle", "approach_person", "analyze_images_vlm", "generate_report",
    "scan_pan", "scan_vision", "update_case",
})


def plan_to_decision(plan: Plan, validated_actions: list[ActionSpec]) -> dict[str, Any]:
    """
    Convert first validated action to a Decision for the existing policy loop.
    Maps planner tools to policy.Action where possible.
    """
    from himpublic.orchestrator.policy import Action, Decision

    if not validated_actions:
        return {
            "decision": Decision(
                action=Action.WAIT,
                params={},
                say=None,
                wait_for_response_s=None,
                mode=plan.phase,
                confidence=plan.confidence,
                used_llm=True,
            ),
            "plan": plan,
            "remaining_actions": [],
        }

    first = validated_actions[0]
    say = None
    wait_s = None
    action = Action.WAIT
    params: dict[str, Any] = {"planner_action": first.tool, "planner_args": first.args}

    if first.tool == "call_out":
        action = Action.SAY
        say = first.args.get("text", "")
    elif first.tool == "ask":
        action = Action.ASK
        say = first.args.get("text", "")
        wait_s = first.args.get("listen_seconds", 15.0)
        if wait_s is None:
            wait_s = 15.0
    elif first.tool == "listen":
        action = Action.WAIT
        wait_s = first.args.get("seconds", 2.0)
    elif first.tool == "rotate":
        action = Action.ROTATE_LEFT if first.args.get("deg", 0) > 0 else Action.ROTATE_RIGHT
    elif first.tool == "walk_forward":
        action = Action.FORWARD_SLOW
    elif first.tool == "wait":
        action = Action.WAIT
    elif first.tool == "capture_image":
        target = first.args.get("target", "full_body")
        count = first.args.get("count", 1)
        params["capture_views"] = [target] * count
        action = Action.SAY
        say = f"Capturing {count} image(s) of {target}."
    elif first.tool in DISPATCH_ONLY_TOOLS:
        action = Action.WAIT

    return {
        "decision": Decision(
            action=action,
            params=params,
            say=say,
            wait_for_response_s=wait_s,
            mode=plan.phase,
            confidence=plan.confidence,
            used_llm=True,
        ),
        "plan": plan,
        "remaining_actions": validated_actions[1:],
    }
