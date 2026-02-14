# Wizard-of-Oz Pipeline

Pure Python pipeline for **camera + mic** demos without a robot. Continuously reads frames, runs placeholder perception (key toggles: `h` human, `d` debris, `i` injury), and transitions through phases **SEARCH → APPROACH → DEBRIS → INJURY → REPORT**. Every robot action (navigate, speak, clear_debris, scan_injuries, send_report) calls a **placeholder** that logs the call and can wait for Enter to simulate completion. Teammates replace the action layer with real implementations later.

## Setup (< 2 minutes)

```bash
cd wizard_oz
pip install -r requirements.txt
```

## Run (copy-paste)

```bash
python -m src.main --show --typed-mic --manual
```

- **--show**: Show webcam window with overlay (phase, last action, toggles).
- **--typed-mic**: Reserved for typed transcript input.
- **--manual**: After each action, press Enter to simulate the action completing.

### Keys

| Key | Effect |
|-----|--------|
| **h** | Toggle "human detected" (move SEARCH → APPROACH) |
| **d** | Toggle "debris detected" (triggers clear_debris in DEBRIS phase) |
| **i** | Toggle "injury findings" (included in report) |
| **n** | Force next phase (demo shortcut) |
| **q** | Quit |

### Headless (no webcam)

```bash
python -m src.main --no-show
```

Uses a blank frame if the camera is unavailable; toggles and phase advances still work if you drive the state machine another way (e.g. tests).

### Optional

- **--save-video**  
  Save frames to `artifacts/video.avi` (default path; override with **--save-video-path**).
- **--max-steps N**  
  Stop after N ticks (0 = no limit).

## Logs and artifacts

- **Action log**: `artifacts/action_calls.jsonl` — one JSON line per action (`action`, `args`, `reason`).
- **Reports**: `artifacts/reports/report_<timestamp>.json` and `artifacts/reports/snapshot.jpg` when the run reaches REPORT.

## Docs

- **docs/wizard_of_oz.md** — Approach and how to plug in real actions/perception.
- **docs/action_api.md** — Action signatures and expected behavior.
- **docs/demo_script.md** — 60–90 second demo: exact command and key order.

## Test

```bash
python -m pytest tests/test_smoke.py -v
```

Or:

```bash
python -c "from tests.test_smoke import test_smoke_headless; test_smoke_headless(); print('OK')"
```

Smoke test runs the state machine in headless mode with mock frames and key toggles and verifies it can run through all phases without crashing.
