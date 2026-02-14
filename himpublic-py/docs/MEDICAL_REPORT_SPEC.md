# Medical Report to Command Center — Spec

Schema-driven medical / SAR incident report (Open Evidence style). Every claim can be traced to observations via evidence IDs.

## Overview

The robot produces a **preliminary assessment** (not a definitive diagnosis). The report is consumed by an operations center. It includes incident meta, location & access, patient summary, ABCDE findings, suspected injuries, hazards, media evidence, provenance table, uncertainties, and recommended next actions. A disclaimer states that this is automated and must be confirmed by a qualified responder.

## Report Sections

### A) Header / Incident Meta

| Field | Description |
|-------|-------------|
| report_id | Unique report identifier |
| session_id | Session (mission) identifier |
| timestamp_start / timestamp_end | Time range of the incident window |
| timezone | e.g. UTC |
| robot_id, operator_id | Identifiers |
| environment_label | Building / floor / room if known |

### B) Location & Access

- **location_estimate** — Best-known location (text).
- **coordinates** — If available (e.g. x,y or lat,lon).
- **location_derivation** — How location was derived: visual landmarks, operator note, last known waypoint, audio direction.
- **access_constraints** — Blocked doors, stairs, narrow passages, rubble.
- **suggested_approach_route** — Plain English route suggestion.
- All location claims may cite **evidence_ids** (e.g. [E12], [E15]).

### C) Patient Summary (1–2 lines)

- **one_liner** — Short summary.
- **estimated_age_range** / **estimated_sex** — If inferred; must be marked as estimated.
- **consciousness** — Responsive to voice / pain / none.
- **primary_concern** — e.g. “possible bleeding from left forearm; limited mobility”.
- **triage_category** — START/JumpSTART-ish: Immediate / Delayed / Minimal / Expectant.
- **overall_confidence** + **confidence_explanation**.

### D) Findings

**ABCDE checklist** — For each of Airway, Breathing, Circulation, Disability, Exposure:

- status, evidence refs, confidence, notes.

**Suspected injuries** — For each:

- injury_type (laceration, burn, fracture suspected, crush injury suspected, etc.)
- body_location (left forearm, right leg, head, torso)
- severity_estimate (mild / moderate / severe) + confidence
- rationale (what cues led to this)
- immediate_actions_recommended (pressure, immobilize, evacuate priority) — **suggestions only**, not medical orders.

**Hazards nearby** — fire/smoke, unstable debris, downed wires, gas smell, water, etc.; risk level + evidence.

### E) Media Evidence

- **Scene Overview** images (wide).
- **Injury Close-ups** (if available).
- Each image: file path (relative), timestamp, caption, evidence_id.
- Audio: transcript snippet (short), timestamp, evidence_id, confidence. Do not dump full transcripts; summarize and link to file.

### F) Evidence & Provenance (Open Evidence style)

A table of Evidence Items:

- evidence_id
- type (image / audio / text / model_output / operator_note)
- timestamp
- source (camera, mic, operator, model name)
- file_path (if any)
- confidence (if applicable)
- summary

Every major claim in the report should cite evidence_ids (e.g. “Possible arterial bleed [E12][E14]”).

### G) Uncertainty / Assumptions

- Explicit list of uncertain items and why.
- Alternative hypotheses when relevant (e.g. “fracture vs sprain”).

### H) Recommended Next Actions (Command Center)

- Top 5 action bullets, ordered by urgency.
- Include safety warnings for responders (e.g. “Unstable debris; approach from east only”).

### I) Disclaimer

Fixed text: *“Automated preliminary assessment. Not a medical diagnosis. Confirm by qualified responder.”*

## Confidence Rules (ReportConfig)

- **confidence_likely_threshold** (default 0.7): ≥ this → wording “likely”.
- **confidence_possible_threshold** (default 0.4): ≥ this → “possible”; below → “uncertain”.
- Renderer uses these for consistent wording; raw confidence values still appear in tables.

## Evidence Log

- Append-only **JSONL** per session: `sessions/<session_id>/evidence.jsonl`.
- **add_evidence(...)** returns an evidence_id (E1, E2, …).
- Each record: id, timestamp, type, source, file_path, confidence, summary, model_metadata.
- The report’s Evidence & Provenance section is built from this log so every claim is traceable.

## Image Handling

- Code accepts a **list of image file paths** or list of dicts with `file_path`, `caption`, `section`, `timestamp`, `evidence_id`.
- Helper **assign_image_captions_and_evidence(image_paths, evidence_log, section, captions)** registers each image in the evidence log and returns dicts with evidence_id and caption for the report.
- Markdown uses relative paths and captions; images are not embedded as base64 in the spec (optional elsewhere).

## Config Knobs (ReportConfig)

| Option | Default | Description |
|--------|---------|-------------|
| include_pdf | False | If True and a PDF util is added later, generate PDF; currently no PDF in repo. |
| include_raw_transcripts | False | If True, include full transcript file refs in audio section. |
| max_images_per_section | 10 | Cap images per section (scene / injury). |
| confidence_likely_threshold | 0.7 | Wording “likely” above this. |
| confidence_possible_threshold | 0.4 | Wording “possible” above this. |

## Integration (Orchestrator)

```python
from himpublic.reporting.render_medical_report import generate_medical_report

session_ctx = {
    "session_id": "sess_123",
    "report_id": "report_456",
    "timestamp_start": start_ts,
    "timestamp_end": end_ts,
    "robot_id": "robot-1",
    "operator_id": "op-1",
    "timezone": "UTC",
    "environment_label": "Building A, Floor 2, Room 204",
}
observations = {
    "location_estimate": "Corridor near stairwell B",
    "consciousness": "responsive to voice",
    "primary_concern": "possible bleeding left forearm; limited mobility",
    "triage_category": "Delayed",
    "overall_confidence": 0.75,
    "suspected_injuries": [...],
    "hazards_nearby": [...],
    "recommended_actions": [...],
}
images = ["path/to/scene.jpg", {"file_path": "path/to/injury.jpg", "section": "injury_closeup", "caption": "Left forearm"}]
audio = [{"transcript_snippet": "My arm is bleeding", "timestamp": 1234.5, "confidence": 0.9}]

report_md_path, pdf_path = generate_medical_report(
    session_ctx, observations, images, audio,
    model_outputs=None,
    artifact_paths={"sessions_base": "artifacts/sessions", "images_relative": "images"},
)
# pdf_path is None (no PDF util). report_md_path = sessions/<session_id>/reports/medical_report.md
```

## Output Paths

- **Markdown:** `sessions/<session_id>/reports/medical_report.md`
- **Evidence log:** `sessions/<session_id>/evidence.jsonl`
- **PDF:** Optional; not generated in current codebase.

## Prompt-agnostic Design

The schema and renderer work whether the robot is doing rubble removal, injury scan, or “found person” only. Omit or leave empty any section that does not apply (e.g. no audio → audio section omitted or empty).
