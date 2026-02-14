# Medical / SAR Incident Report

## Incident Meta
- **Report ID:** report_sample_001
- **Session ID:** sample_session_001
- **Timestamp range:** 1707890123 – 1707890423 (UTC)
- **Robot:** robot-1
- **Operator:** op-1
- **Environment:** Building A, Floor 2, Room 204

## Location & Access
- **Best-known location:** Corridor near stairwell B, east wing
- **Coordinates:** x=12.4, y=8.2
- **Derivation:** Visual landmarks (exit sign); last known waypoint
- **Access constraints:** Debris near door; narrow passage
- **Suggested approach:** Enter from east corridor, turn left at exit sign; avoid rubble pile on right.

## Patient Summary
One adult, seated, responsive to voice; possible bleeding left forearm.
(Estimated age: adult; Estimated sex: unknown)
- **Consciousness:** responsive to voice
- **Primary concern:** possible bleeding from left forearm; limited mobility
- **Triage category:** Delayed
- **Overall confidence:** 0.72 — Clear verbal response; visual cue consistent with forearm injury.

## ABCDE Findings
| Component | Status | Evidence | Confidence | Notes |
|----------|--------|----------|------------|-------|
| Airway | patent | E1 | 0.90 | speech clear |
| Breathing | adequate | E1 | 0.85 | no distress |
| Circulation | possible bleeding | E2, E3 | 0.70 | forearm |
| Disability | alert | E1 | 0.90 | — |
| Exposure | partial | E2 | 0.60 | left arm visible |

## Suspected Injuries
| Type | Body location | Severity | Confidence | Rationale | Evidence |
|------|----------------|----------|------------|-----------|----------|
| laceration | left forearm | moderate | 0.70 | Visible wound and blood on sleeve; person reported 'my arm is bleeding'. | E2, E3, E4 |
- **left forearm:** Apply pressure with clean dressing; Consider elevation

## Hazards Nearby
| Description | Risk level | Evidence |
|-------------|------------|----------|
| Unstable debris near doorway | medium | E1 |

## Media Evidence
### Scene Overview
- **E1** — Wide view of corridor and victim location (t=1771108300)
  ![](images/images/scene_overview_001.jpg)
- **E2** — Approach view (t=1771108300)
  ![](images/images/scene_overview_002.jpg)
### Injury Close-ups
- **E3** — Left forearm possible laceration (t=1771108300)
  ![](images/images/injury_forearm_001.jpg)
### Audio
- **E4** (t=1707890200, conf=0.92): My arm is bleeding. I can't move it much.

## Evidence & Provenance
| evidence_id | type | timestamp | source | file_path | confidence | summary |
|-------------|------|-----------|--------|-----------|------------|--------|
| E1 | image | 1771108300 | camera | images/scene_overview_001.jpg | 0.00 | Wide view of corridor and victim location |
| E2 | image | 1771108300 | camera | images/scene_overview_002.jpg | 0.00 | Approach view |
| E3 | image | 1771108300 | camera | images/injury_forearm_001.jpg | 0.00 | Left forearm possible laceration |
| E4 | audio | 1707890200 | mic | — | 0.92 | My arm is bleeding. I can't move it much. |

## Uncertainty / Assumptions
- **Severity of bleeding** — No direct wound inspection
  Alternatives: superficial vs arterial
- **Fracture vs soft tissue** — Limited mobility could be either
  Alternatives: fracture; sprain; pain only

## Recommended Next Actions (Command Center)
1. [high] Dispatch medic to location; bring tourniquet and pressure dressing
2. [medium] Stabilize debris before entry if possible **[SAFETY WARNING]**
3. [high] Prioritize evacuation once stable

---

*Automated preliminary assessment. Not a medical diagnosis. Confirm by qualified responder.*
