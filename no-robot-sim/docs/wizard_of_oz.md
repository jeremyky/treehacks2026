# Wizard-of-Oz Pipeline

## Approach

The pipeline runs **without a robot**: you walk around with a laptop (camera + optional mic). The software:

1. **Continuously reads** camera frames (and optionally mic input).
2. **Runs placeholder perception** (or simple CV): human, debris, injury "detection" driven by key toggles (`h` / `d` / `i`) for demo.
3. **Transitions through phases**: SEARCH → APPROACH → DEBRIS_ASSESS → INJURY_SCAN → REPORT.
4. **Calls a placeholder action layer** for every robot/operator action: navigate, speak, clear_debris, scan_injuries, send_report. Each call is **logged** (print + JSONL) and can **wait for Enter** to simulate the action completing.

So you are the "wizard": you press keys to simulate detections, and the system runs the full state machine and action API as if the robot existed. Teammates can later **replace stubs with real implementations** without changing the state machine or main loop.

## How Teammates Plug In Real Actions

1. **Action layer**  
   Implement `ActionClient` (see `src/actions/action_client.py`) with real hardware:
   - `navigate_to` → robot base or simulator
   - `speak` → TTS or speaker
   - `clear_debris` → arm or pusher
   - `scan_injuries` → trigger camera/classifier
   - `send_report` → HTTP to command center or save

   Swap `PlaceholderActionClient` for your client in `main.py` (or inject via config). The state machine only depends on the `ActionClient` interface.

2. **Perception**  
   Replace the placeholder detectors with real models:
   - `detect_humans(frame) -> list[Detection]` in `src/perception/human_detector.py`
   - `detect_debris(frame) -> list[DebrisFinding]` in `src/perception/debris_detector.py`
   - `detect_injuries(frame) -> list[InjuryFinding]` in `src/perception/injury_detector.py`

   Signatures are fixed; keep return types so the state machine and logging stay unchanged.

3. **Config**  
   `src/config.py` and CLI flags (`--manual`, `--show`, etc.) stay; add flags for robot URL, API keys, etc., and pass them into your `ActionClient` and detectors.

## Logs and Artifacts

- **Action calls**: every action is printed as `ACTION[name](...)` and appended to `./artifacts/action_calls.jsonl`.
- **Reports**: when the run reaches REPORT, a JSON report is written to `./artifacts/reports/report_<timestamp>.json` and one snapshot image to `./artifacts/reports/snapshot.jpg`.
- **Manual confirm**: with `--manual`, each action waits for Enter before returning success, so you can simulate variable action duration.

## Running

See **demo_script.md** for a 60–90 second demo. Quick start:

```bash
pip install -r requirements.txt
python -m src.main --show --typed-mic --manual
```

Keys: `h` human, `d` debris, `i` injury, `n` next phase, `q` quit.
