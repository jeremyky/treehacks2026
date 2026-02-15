"""
Speech-first triage: priority and actions from victim statement + Q/A.

Vision findings are supporting evidence only; they do not set severity or
downgrade urgency. Priority is computed from what the victim says and key answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schemas import Finding, RankedSuspectedInjury

# START/SALT-style buckets (human-legible for responders)
TriagePriorityLevel = str  # "Immediate" | "Urgent" | "Delayed" | "Minor" | "Expectant"


@dataclass
class SpeechFirstTriage:
    """Output of speech-first triage: priority, rationale, ranked injuries, actions."""
    priority: TriagePriorityLevel
    rationale: str
    chief_complaint: str
    mechanism_context: str
    suspected_injuries: list[RankedSuspectedInjury] = field(default_factory=list)  # from schemas
    do_asap: list[str] = field(default_factory=list)
    for_responders: list[str] = field(default_factory=list)
    vision_findings_supporting: list[str] = field(default_factory=list)  # no severity, supporting only


def _normalize(s: str) -> str:
    return (s or "").lower().strip()


def _has_any(text: str, *phrases: str) -> bool:
    t = _normalize(text)
    return any(p in t for p in phrases)


def compute_speech_first_triage(
    victim_statement: str,
    victim_answers: dict[str, str],
    vision_findings: list[Finding],
    mechanism_context: str = "",
) -> SpeechFirstTriage:
    """
    Compute triage priority and actions from victim statement + answers.
    Vision findings are summarized as supporting evidence only (no severity).
    """
    statement = _normalize(victim_statement or "")
    answers = {k: _normalize(v) for k, v in (victim_answers or {}).items()}
    combined = statement + " " + " ".join(answers.values())

    # ── Chief complaint: victim's words ────────────────────────
    chief = (victim_statement or "").strip() or "(No victim statement.)"

    # ── Mechanism / context ────────────────────────────────────
    mechanism = mechanism_context or ""
    if _has_any(combined, "rubble", "debris", "fell on", "collapse", "crush", "trapped", "pinned"):
        mechanism = (mechanism + " Debris impact; possible entrapment.").strip()
    if _has_any(combined, "bleeding", "blood", "cut", "lacerat"):
        mechanism = (mechanism + " Bleeding reported.").strip()
    if _has_any(combined, "broke", "fracture", "broken", "dislocat"):
        mechanism = (mechanism + " Possible fracture/dislocation per victim.").strip()
    if not mechanism:
        mechanism = "Context from victim and scene."

    # ── Priority (speech-first) ───────────────────────────────
    priority = "Delayed"
    rationale_parts: list[str] = []

    bleeding = _has_any(combined, "bleeding", "blood", "bleed")
    heavy_bleeding = bleeding and (
        _has_any(answers.get("bleed_severity", ""), "heavy", "spurting", "soaking")
        or _has_any(statement, "heavy", "a lot", "spurting")
    )
    fracture_suspected = _has_any(combined, "broke", "broken", "fracture", "break")
    severe_pain = _has_any(combined, "severe", "10", "9", "8", "really bad", "extreme") or "pain" in combined
    crush_trapped = _has_any(combined, "crush", "trapped", "pinned", "rubble fell", "under")
    breathing = _has_any(combined, "breathing", "can't breathe", "trouble breathing", "short of breath")
    dizzy_faint = _has_any(combined, "dizzy", "faint", "pass out", "lightheaded")
    numbness = _has_any(combined, "numb", "tingling", "blue", "cold", "can't feel")

    if heavy_bleeding or (bleeding and dizzy_faint):
        priority = "Immediate"
        rationale_parts.append("Uncontrolled or significant bleeding risk.")
    elif bleeding and (fracture_suspected or severe_pain):
        priority = "Urgent"
        rationale_parts.append("Bleeding reported with severe pain or suspected fracture.")
    elif fracture_suspected and (severe_pain or numbness):
        priority = "Urgent"
        rationale_parts.append("Suspected fracture with severe pain or neurovascular concerns.")
    elif breathing or dizzy_faint:
        priority = "Urgent"
        rationale_parts.append("Airway/breathing or circulatory concerns reported.")
    elif crush_trapped:
        priority = "Urgent"
        rationale_parts.append("Crush/entrapment; escalate and document duration.")
    elif bleeding or fracture_suspected:
        priority = "Urgent"
        rationale_parts.append("Bleeding and/or suspected fracture per victim.")
    elif severe_pain:
        priority = "Delayed"
        rationale_parts.append("Significant pain reported.")
    else:
        rationale_parts.append("Assessment based on victim report and context.")

    rationale = " ".join(rationale_parts) if rationale_parts else "Based on victim statement and triage answers."

    # ── Ranked suspected injuries (differential) ────────────────
    suspected: list[RankedSuspectedInjury] = []

    if bleeding:
        suspected.append(RankedSuspectedInjury(
            injury="External bleeding (laceration/abrasion)",
            likelihood="likely" if _has_any(statement, "bleeding", "blood") else "possible",
            evidence_victim=True,
            evidence_vision=any("blood" in f.prompt or "bleeding" in f.prompt or f.signals.get("red_ratio", 0) > 0.05 for f in vision_findings),
            evidence_context=bool(mechanism),
        ))

    if fracture_suspected or _has_any(combined, "elbow", "arm", "dislocat"):
        suspected.append(RankedSuspectedInjury(
            injury="Elbow or limb fracture / dislocation",
            likelihood="likely" if fracture_suspected else "possible",
            evidence_victim=True,
            evidence_vision=False,
            evidence_context=bool(mechanism),
        ))

    if bleeding and fracture_suspected:
        suspected.append(RankedSuspectedInjury(
            injury="Open fracture (bone + wound)",
            likelihood="possible",
            evidence_victim=True,
            evidence_vision=False,
            evidence_context=True,
        ))

    if numbness or _has_any(combined, "blue", "cold", "tingling"):
        suspected.append(RankedSuspectedInjury(
            injury="Neurovascular injury (nerve/artery compromise)",
            likelihood="possible",
            evidence_victim=True,
            evidence_vision=False,
            evidence_context=False,
        ))

    if crush_trapped:
        suspected.append(RankedSuspectedInjury(
            injury="Crush syndrome / crush-related complications",
            likelihood="possible",
            evidence_victim=True,
            evidence_vision=False,
            evidence_context=True,
        ))

    if bleeding and (heavy_bleeding or dizzy_faint):
        suspected.append(RankedSuspectedInjury(
            injury="Shock risk",
            likelihood="possible",
            evidence_victim=True,
            evidence_vision=False,
            evidence_context=False,
        ))

    # ── Do ASAP (minutes) ─────────────────────────────────────
    do_asap: list[str] = []
    do_asap.append("Call for human responders immediately; transmit location and report possible major bleed + suspected fracture if applicable.")
    if bleeding:
        do_asap.append("Control bleeding: instruct victim to apply firm direct pressure with cloth/dressing; keep pressure continuous.")
        do_asap.append("If bleeding is life-threatening and equipment available: tourniquet above wound, not on a joint (responder guidance).")
    if fracture_suspected or _has_any(combined, "broke", "broken", "elbow"):
        do_asap.append("Immobilize suspected fracture: minimize movement; support with sling/splint if available.")
    do_asap.append("Screen red flags: 'Is bleeding soaking through in under a minute or spurting?' (upgrade to Immediate if yes).")
    do_asap.append("Screen: 'Can you wiggle fingers? Any numbness or tingling?' (vascular/nerve risk).")
    do_asap.append("Screen: 'Any trouble breathing, chest pain, or feeling faint?' (shock/airway).")
    do_asap.append("Shock prevention: keep victim warm, reassure, keep still.")

    # ── For responders on arrival ─────────────────────────────
    for_resp: list[str] = []
    if bleeding:
        for_resp.append("Hemorrhage control: hemostatic dressing, pressure bandage, tourniquet if indicated.")
    for_resp.append("Neurovascular exam of limb: pulses, cap refill, sensation, motor function.")
    for_resp.append("Immobilization + analgesia + imaging: splint, pain control, X-ray, ortho evaluation.")
    if bleeding or any("open" in si.injury.lower() for si in suspected):
        for_resp.append("Open wound/open fracture precautions: cover wound, infection/tetanus (responders).")
    if crush_trapped:
        for_resp.append("Crush/entrapment: if prolonged compression, plan treatment around extrication risk; document and warn.")

    # ── Vision findings: supporting only (no severity) ─────────
    vision_supporting: list[str] = []
    for f in vision_findings:
        region = f.body_region or "reported area"
        desc = f"Possible blood-like or injury cue near {region} (visual-only, {f.confidence_label} confidence)."
        vision_supporting.append(desc)

    return SpeechFirstTriage(
        priority=priority,
        rationale=rationale,
        chief_complaint=chief,
        mechanism_context=mechanism,
        suspected_injuries=suspected,
        do_asap=do_asap,
        for_responders=for_resp,
        vision_findings_supporting=vision_supporting,
    )
