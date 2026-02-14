# What We Report to the Command Center (and medical report ideas)

## What we report today

### 1. Telemetry (1 Hz)

The agent POSTs to **`/event`** once per second with a heartbeat payload:

- `event`: `"heartbeat"`
- `timestamp`, `phase`, `phase_label`, `mode`
- `boot_ready`, `degraded_mode`
- `num_persons`, `confidence`, `primary_person_center_offset`

No images in this payload; it’s status only.

### 2. Event-driven posts (FOUND_PERSON, HEARD_RESPONSE, etc.)

When something notable happens we:

1. **POST JSON to `/event`** with:
   - `event`: e.g. `found_person`, `heard_response`, `possible_injury`, `operator_request`, `heartbeat` (with snapshot)
   - `timestamp`, `snapshot_paths` (local paths on the agent machine)
   - Event-specific `meta`: e.g. `num_persons`, `confidence`, `transcript`

2. **POST JPEGs to `/snapshot`** (multipart): one or more keyframes from the ring buffer, with metadata (event type, etc.). Server saves them under `./data/snapshots/` and keeps the latest path.

So right now: **events are JSON; images are separate**. The “document” the command center has is effectively “last event blob + last snapshot path.” There is no single, self-contained **report document** that ties together situation description, victim response, and images for a medical or triage workflow.

---

## Where this falls short for medical use

- No **single report doc** that a medic or a medical chatbot can open and read.
- No **narrative** (e.g. “One adult, seated, stated ‘my leg hurts’; possible injury indicators on lower leg”).
- No **structured diagnosis/triage** fields (e.g. severity, body region, recommended action).
- **Images** are stored separately; they aren’t embedded in or tightly bound to the report (e.g. by reference in one JSON/PDF).

---

## Ideas: medical chatbot + report with location, situation, and images

### 1. Define a “triage / incident report” payload

One JSON (or PDF generated from it) that a medical chatbot or human can consume:

- **Identity / session**: `report_id`, `agent_id`, `timestamp`, `phase` when report was generated.
- **Location / situation** (for “accurately describe location and situation”):
  - `location_description`: free text (e.g. “indoor, room 2, near window” or “GPS + building floor” if you have it).
  - `situation_summary`: 1–3 sentences (e.g. “One person detected, seated; debris nearby; person responded to verbal prompt.”).
- **Victim / subject**:
  - `victim_response`: exact transcript of what the person said (e.g. from HEARD_RESPONSE).
  - `injury_indicators`: list of `{ body_region, type, severity_estimate, confidence }` (from injury detector or LLM).
- **Images in the doc**:
  - `image_refs`: list of `{ id, path_or_url, caption, timestamp }` so the report references specific frames (e.g. “frontal view”, “after approach”).
  - Optionally inline **base64** thumbnails in the JSON for a truly self-contained doc (heavier).
- **Optional “diagnosis” / triage** (for a medical chatbot):
  - `triage_summary`: short free text (e.g. “Possible lower-limb injury; conscious and responsive; suggest immobilization and evacuation.”).
  - `recommended_actions`: list of strings (e.g. “Stabilize leg”, “Request medic”).

You’d **generate this report** when leaving ASSIST_COMMUNICATE or when the operator asks for a “final report” (e.g. on REPORT phase or on demand), and **POST it to the command center** (e.g. `POST /report` or `/triage_report`).

### 2. Use an LLM to produce the narrative and triage

- **Inputs**: phase log, last observation (num_persons, confidence), victim transcript, any injury findings, optional scene caption.
- **Outputs**: `situation_summary`, `location_description` (if you don’t have GPS/indoor positioning), `triage_summary`, `recommended_actions`.
- **Prompt**: e.g. “You are a triage assistant. Given: [structured data]. Write a short situation summary and triage note. Be concise and medical.” You can enforce JSON so the command center or chatbot parses it.

This gives you **accurate, readable description of location and situation** plus a first-pass “diagnosis” style text.

### 3. Include images in the doc

- **Option A – References**: Report JSON includes `image_refs` with paths or URLs. Command center (or a small backend) resolves them and builds a PDF/HTML doc that shows the narrative + images.
- **Option B – Base64**: Report JSON includes `images: [ { mime, data_base64 } ]`. Single request; doc is self-contained; good for sending to an external medical chatbot API.
- **Option C – Multipart**: `POST /report` as multipart: one part = JSON report (with `image_refs` pointing to part names), other parts = JPEGs. Server stores images and saves the report with stable refs.

Recommendation: **Option A** for simplicity (report + existing snapshot paths); add **Option B** later if you need a single blob for an external API.

### 4. Command center and medical chatbot

- **Command center** (current FastAPI app):
  - Add `POST /report` (or `/triage_report`) that accepts the structured report JSON (and optionally images). Store the latest report and optionally write `reports/<report_id>.json` (+ images) so the UI can show “last incident report” with narrative + images.
  - Add a simple **“Report”** view: show `situation_summary`, `victim_response`, `triage_summary`, and linked images.
- **Medical chatbot**:
  - **Internal**: Command center UI has a “Chat” tab; backend sends the **last report** (narrative + image_refs or base64) to an LLM with a medical/triage system prompt; LLM answers questions or suggests actions.
  - **External**: Same report (with images) is sent to an external medical API (e.g. hospital triage endpoint) as one JSON/PDF.

### 5. Minimal next steps in code

- Add a **report builder** in the agent (or a small `reporting` module): when generating the “final” report (e.g. on transition to REPORT or on operator request), build the structured payload above from:
  - `phase_log`, `last_observation`, `last_response` (transcript), injury findings (if any), and 1–3 keyframes (paths or base64).
- Add **LLM call** (or stub) that takes that structured data and returns `situation_summary`, `triage_summary`, `recommended_actions`.
- **POST** that report to the command center (`POST /report`); command center stores it and, if you have a frontend, displays it with images.

That gives you a single **document** that accurately describes location and situation, includes images, and is ready for a medical chatbot or human medic.
