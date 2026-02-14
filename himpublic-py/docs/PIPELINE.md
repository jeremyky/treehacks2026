# Rescue Pipeline — Strict Sequential Execution

## Overview

The rescue pipeline enforces a **strict, reproducible phase order**:

```
DEPLOY → SEARCH_HAIL → APPROACH_CONFIRM → DEBRIS_CLEAR →
TRIAGE_DIALOG_SCAN → REPORT_SEND → MONITOR_WAIT
```

There is **no way to skip, reorder, or bypass phases** unless an explicit
`--force_phase` override flag is used (logged as a deliberate override).

---

## How Ordering Is Enforced

Phases are stored in a **Python list** (`PIPELINE_PHASES` in `phases.py`)
and executed via a **sequential `for` loop** in `PipelineRunner.run()`.
There is no dispatch table, no event bus, and no mechanism for a phase
handler to jump to an arbitrary other phase.  The only way to advance is
to return a `PhaseResult` from the current handler.

```python
for idx, phase_def in enumerate(self._phases):
    result = self._execute_phase(ctx, phase_def, idx)
    # ... validate, store, next iteration
```

This means:
- **No skipping**: every phase in the list is visited.
- **No reordering**: the list order *is* the execution order.
- **No ad-hoc transitions**: phase handlers cannot call other phases.
- **Explicit override only**: `--force_phase X` marks all phases before X
  as `SKIPPED` with a log entry.  This is for debugging only.

---

## Phase Definitions

### 1. DEPLOY (Self-check)
| | |
|---|---|
| **Entry** | Pipeline start (no preconditions) |
| **Action** | Verify sensors (camera, mic, speaker, comms) |
| **Success output** | `deploy_status` = "ready" or "degraded" |
| **Failure** | Retry ×2, then proceed degraded |
| **Exit** | `deploy_status` set → advance to SEARCH_HAIL |

### 2. SEARCH_HAIL
| | |
|---|---|
| **Entry** | `deploy_status` ∈ {"ready", "degraded"} |
| **Action** | Rotate, scan, hail with voice, listen for response |
| **Success output** | `person_detected=True`, `person_confidence`, `hail_response` |
| **Failure** | Retry ×5 (with 2s cooldown), then ABORT |
| **Exit** | Person detected → advance to APPROACH_CONFIRM |

### 3. APPROACH_CONFIRM
| | |
|---|---|
| **Entry** | `person_detected=True` |
| **Action** | Navigate to person, re-detect, confirm identity |
| **Success output** | `approach_confirmed=True`, `standoff_established=True` |
| **Failure** | Retry ×3, then ABORT |
| **Exit** | Confirmed → advance to DEBRIS_CLEAR |

### 4. DEBRIS_CLEAR
| | |
|---|---|
| **Entry** | `approach_confirmed=True` |
| **Action** | Scan for debris, attempt to clear if possible |
| **Success output** | `debris_status` ∈ {"clear", "blocked_cleared", "blocked_not_clearable"} |
| **Failure** | Retry ×2, then proceed degraded (mark status, continue) |
| **Exit** | Status assessed → advance to TRIAGE_DIALOG_SCAN |

### 5. TRIAGE_DIALOG_SCAN
| | |
|---|---|
| **Entry** | `approach_confirmed=True` |
| **Action** | Medical triage dialogue (via `TriageDialogueManager`), body scan images |
| **Success output** | `triage_answers`, `patient_state`, `scan_images`, `transcript` |
| **Failure** | Retry ×2, then proceed degraded (partial data) |
| **Exit** | Triage data collected → advance to REPORT_SEND |

### 6. REPORT_SEND
| | |
|---|---|
| **Entry** | `triage_answers` or `patient_state` non-empty |
| **Action** | Compile structured report, send to command center, save to disk |
| **Success output** | `report_path`, `report_sent`, `incident_id` |
| **Failure** | Retry ×3 (3s cooldown); always saves to disk as fallback |
| **Exit** | Report persisted → advance to MONITOR_WAIT |

### 7. MONITOR_WAIT
| | |
|---|---|
| **Entry** | `report_path` set |
| **Action** | Stay with victim, relay operator messages, watch for changes |
| **Success output** | `monitor_active=True` |
| **Failure** | N/A (no retry needed) |
| **Exit** | Operator handoff or mission command |

---

## MissionContext — Cross-Phase Data

The `MissionContext` dataclass carries all accumulated outputs forward:

| Field | Set by | Used by |
|---|---|---|
| `deploy_status` | DEPLOY | SEARCH_HAIL (precondition) |
| `sensors_available` | DEPLOY | all phases (capability check) |
| `person_detected` | SEARCH_HAIL | APPROACH_CONFIRM (precondition) |
| `person_confidence` | SEARCH_HAIL, APPROACH | REPORT_SEND |
| `person_location_hint` | SEARCH_HAIL | REPORT_SEND |
| `approach_confirmed` | APPROACH_CONFIRM | DEBRIS_CLEAR, TRIAGE (precondition) |
| `debris_status` | DEBRIS_CLEAR | REPORT_SEND |
| `triage_answers` | TRIAGE_DIALOG_SCAN | REPORT_SEND (precondition) |
| `patient_state` | TRIAGE_DIALOG_SCAN | REPORT_SEND |
| `scan_images` | TRIAGE_DIALOG_SCAN | REPORT_SEND |
| `transcript` | SEARCH_HAIL through MONITOR | REPORT_SEND, artifacts |
| `report_payload` | REPORT_SEND | MONITOR_WAIT |
| `report_path` | REPORT_SEND | MONITOR_WAIT (precondition) |

---

## Retry / Failure Behavior

Each phase has a `RetryPolicy`:

```python
RetryPolicy(
    max_attempts=3,      # total attempts (not retries)
    cooldown_s=2.0,      # sleep between retries
    allow_degraded=False, # if True, proceed after exhausting retries
    fallback_status=PhaseStatus.ABORT  # what happens when retries run out
)
```

**Specific failure behaviors:**

| Phase | Max attempts | Cooldown | On exhaust |
|---|---|---|---|
| DEPLOY | 2 | 1s | Proceed degraded |
| SEARCH_HAIL | 5 | 2s | **ABORT** (no person found) |
| APPROACH_CONFIRM | 3 | 2s | **ABORT** |
| DEBRIS_CLEAR | 2 | 1s | Proceed degraded |
| TRIAGE_DIALOG_SCAN | 2 | 2s | Proceed degraded (partial data) |
| REPORT_SEND | 3 | 3s | Proceed degraded (disk fallback) |
| MONITOR_WAIT | 1 | 0s | N/A |

Every attempt is logged to `missions/<run_id>/log.jsonl` with:
- Phase name, attempt number, status, elapsed time, reason
- All outputs and evidence keys

---

## Running the Pipeline

### Demo mode (simulated, no hardware)
```bash
cd himpublic-py
python -m himpublic.pipeline.cli --mode demo
```

### With custom run ID and output path
```bash
python -m himpublic.pipeline.cli --mode demo --run_id my_test_run --out ./my_missions
```

### Explain ordering enforcement
```bash
python -m himpublic.pipeline.cli --explain
```

### Skip to a specific phase (debugging only)
```bash
python -m himpublic.pipeline.cli --mode demo --force_phase TRIAGE_DIALOG_SCAN
```

### Resume from snapshot
```bash
# Load context_snapshot.json, use --force_phase to skip completed phases
python -m himpublic.pipeline.cli --mode demo --force_phase REPORT_SEND
```

---

## Output Artifacts

After a run, `missions/<run_id>/` contains:

```
missions/<run_id>/
├── log.jsonl                 # Structured JSONL log (every transition, timing, metric)
├── report.json               # Final incident report (JSON)
├── report.md                 # Final incident report (Markdown)
├── context_snapshot.json     # Full MissionContext (for resume)
├── transcript.json           # Full dialogue transcript
├── images/
│   ├── debris_scan_front.txt # Debris scan evidence
│   ├── scan_front.txt        # Body scan images
│   ├── scan_left.txt
│   ├── scan_right.txt
│   └── scan_wound_closeup.txt
└── audio/
    └── (audio recordings when available)
```

---

## Plugging In Real Robot Actions

To replace demo placeholders with real hardware:

1. **Each handler checks `ctx.mode`**: `if ctx.mode == "robot":` branch
2. **Import real subsystems** inside the handler (lazy import to avoid deps when not needed)
3. **Modify only the handler body** — the engine, preconditions, and postconditions remain unchanged
4. **Example** (SEARCH_HAIL with real perception):
```python
def _search_hail_handler(ctx: MissionContext) -> PhaseResult:
    if ctx.mode == "robot":
        from himpublic.perception.person_detector import PersonDetector
        from himpublic.io.audio_io import RobotAudioIO
        detector = PersonDetector(...)
        audio = RobotAudioIO()
        # ... real scan, hail, listen ...
    else:
        # demo simulation
        ...
```

The pipeline engine doesn't care *how* a phase does its work — only that it
returns a valid `PhaseResult` and writes its outputs to `MissionContext`.
