"""LLM planner: receives WorldState, outputs JSON Plan."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .schema import WorldState, Plan, ActionSpec, ALLOWED_TOOLS, build_world_state

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are a disaster response robot planner. Your job is to output a short-horizon plan (1–5 actions) each tick. Return JSON only—no markdown, no prose.

## Tool schema (you may ONLY use these tools)

### Navigation / search
- call_out(text: str) — speak out loud to attract attention
- listen(seconds: float) — listen for voice (0.5–20 s)
- rotate(deg: float) — turn in place, bounded per step
- walk_forward(meters: float) — move forward, bounded per step
- scan_pan(deg_total: float, step_deg: float) — rotate + scan
- wait(seconds: float) — wait before next action

### Perception
- scan_vision(mode: "person"|"person+rubble"|"rubble"|"medical_focus") — run vision scan
- capture_image(target: "full_body"|"upper_body"|"lower_body"|"head"|"injury_region", count: int) — capture frames
- analyze_images_vlm(prompt: str) — VLM analysis of captured frames

### Interaction / debris
- push_obstacle(direction: "forward"|"left"|"right"|"forward_left"|"forward_right", strength: "low"|"med") — push debris
- approach_person(target_id: str) — move toward detected person

### Medical / documentation
- ask(text: str) — ask victim a question, then listen
- update_case(fields: dict) — update triage fields (whitelisted keys only)
- generate_report() — compile and send report

## Output format (JSON only)
{
  "phase": "<current phase string>",
  "intent": "<short 1-line intent>",
  "actions": [
    {"tool": "call_out", "args": {"text": "Can you hear me?"}},
    {"tool": "listen", "args": {"seconds": 2.0}},
    ...
  ],
  "rationale": "<1–3 sentences using evidence from state>",
  "confidence": 0.0–1.0
}

## Rules
- Plan 1–5 steps. Replan every tick after execution.
- Use audio first to direct search (call_out, listen), then vision to confirm.
- During medical: ask focused questions, capture images, then summarize.
- Only output tools from the schema above. Never invent new tools.
- Keep actions minimal and evidence-based."""

DEVELOPER_PROMPT = """Current phase: {phase}. Allowed tools this phase: {allowed}.
Evidence: persons={num_persons}, rubble={num_rubble}, heard_voice={heard_voice}, voice_angle={voice_angle}.
Return JSON only."""


def _extract_json(content: str) -> str | None:
    """Extract JSON from model output (handle markdown code blocks)."""
    if not content or not content.strip():
        return None
    s = content.strip()
    if s.startswith("```"):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if match:
            s = match.group(1).strip()
        else:
            lines = s.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines)
    return s


def _parse_plan(raw: dict[str, Any]) -> Plan | None:
    """Parse dict into Plan. Returns None if invalid."""
    if not isinstance(raw, dict):
        return None
    phase = str(raw.get("phase", "")).strip() or "search_localize"
    intent = str(raw.get("intent", "")).strip() or "Continue"
    rationale = str(raw.get("rationale", "")).strip() or ""
    confidence = float(raw.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    actions: list[ActionSpec] = []
    raw_actions = raw.get("actions")
    if isinstance(raw_actions, list):
        for a in raw_actions:
            if not isinstance(a, dict):
                continue
            tool = str(a.get("tool", "")).strip().lower()
            if tool not in ALLOWED_TOOLS:
                logger.warning("[PLANNER] Unknown tool %r, skipping", tool)
                continue
            args = a.get("args")
            if not isinstance(args, dict):
                args = {}
            expected = a.get("expected_observation")
            if expected is not None:
                expected = str(expected).strip() or None
            actions.append(ActionSpec(tool=tool, args=dict(args), expected_observation=expected))

    return Plan(
        phase=phase,
        intent=intent,
        actions=actions,
        rationale=rationale,
        confidence=confidence,
    )


def plan_next_actions(
    world_state: WorldState,
    *,
    api_key: str | None = None,
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
) -> Plan:
    """
    Call LLM to produce plan. On failure or invalid output, returns safe fallback
    (wait 1.0) and logs error.
    """
    from .schema import PHASE_ALLOWED_TOOLS, SAFE_TOOLS_ANY_PHASE

    key = api_key or __import__("os").environ.get("OPENAI_API_KEY")
    if not key or not key.strip():
        logger.debug("[PLANNER] No API key; using fallback wait(1.0)")
        return _fallback_plan(world_state.phase)

    phase = world_state.phase
    allowed = PHASE_ALLOWED_TOOLS.get(phase, SAFE_TOOLS_ANY_PHASE)
    dev_prompt = DEVELOPER_PROMPT.format(
        phase=phase,
        allowed=", ".join(sorted(allowed)),
        num_persons=len(world_state.vision.get("persons", [])),
        num_rubble=len(world_state.vision.get("rubble", [])),
        heard_voice=world_state.audio.get("heard_voice", False),
        voice_angle=world_state.audio.get("voice_angle_deg"),
    )

    user_content = dev_prompt + "\n\nWorldState (JSON):\n" + json.dumps(
        world_state.to_dict(), indent=0, default=str
    )

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("[PLANNER] openai package not installed; using fallback")
        return _fallback_plan(phase)

    client = OpenAI(api_key=key)
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=max(0.0, min(0.4, temperature)),
        )
        choice = response.choices and response.choices[0]
        if not choice or not getattr(choice.message, "content", None):
            logger.warning("[PLANNER] Empty LLM response")
            return _fallback_plan(phase)

        content = choice.message.content
        json_str = _extract_json(content)
        if not json_str:
            logger.warning("[PLANNER] Could not extract JSON from: %s", content[:200])
            return _fallback_plan(phase)

        parsed = json.loads(json_str)
        plan = _parse_plan(parsed)
        if plan is None:
            logger.warning("[PLANNER] Invalid plan structure")
            return _fallback_plan(phase)

        logger.info(
            "[PLANNER] plan phase=%s intent=%s actions=%d confidence=%.2f",
            plan.phase,
            plan.intent[:40] if plan.intent else "-",
            len(plan.actions),
            plan.confidence,
        )
        return plan

    except json.JSONDecodeError as e:
        logger.warning("[PLANNER] JSON parse error: %s", e)
        return _fallback_plan(phase)
    except Exception as e:
        logger.warning("[PLANNER] LLM call failed: %s", e)
        return _fallback_plan(phase)


def _fallback_plan(phase: str) -> Plan:
    """Safe fallback when LLM fails or returns invalid output."""
    return Plan(
        phase=phase,
        intent="Safe fallback",
        actions=[ActionSpec(tool="wait", args={"seconds": 1.0}, expected_observation=None)],
        rationale="LLM unavailable or invalid output; defaulting to wait(1.0)",
        confidence=0.0,
    )
