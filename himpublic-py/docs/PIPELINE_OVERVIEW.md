# Pipeline Overview: Search-and-Rescue System

Summary of the entire pipeline and all components built so far (TreeHacks 2026). Two main stacks: **himpublic-py** (always-on agent with real perception and phase-based mission) and **wizard_oz** (Wizard-of-Oz demo without robot, key-triggered placeholders).

---

## 1. Repo layout

```
treehacks2026/
├── himpublic-py/          # Main Python orchestrator (no ROS)
│   ├── src/himpublic/     # Package: main, orchestrator, perception, io, comms
│   ├── scripts/           # run_command_center.py
│   ├── docs/              # CHANGELOG, DEV_GUIDE, system_prompt, PIPELINE_OVERVIEW
│   └── tests/
├── wizard_oz/             # WoZ demo: camera + placeholders, action stubs
│   ├── src/               # main, config, perception, actions, supervisor
│   ├── docs/              # wizard_of_oz, action_api, demo_script
│   ├── artifacts/         # action_calls.jsonl, reports/
│   └── tests/
└── himpublic-ros/         # Optional ROS2 (separate stack)
```

- **himpublic-py**: Always-on agent; camera/file + optional mic; YOLO person detection; frame store + events; two-layer brain (reflex + LLM policy); phases from Boot through Handoff; command center posting. Runs until Ctrl+C.
- **wizard_oz**: Demo pipeline without robot; continuous camera read; perception and actions are placeholders (key toggles h/d/i); phases SEARCH → APPROACH → DEBRIS → INJURY → REPORT; every action logs to JSONL and can wait for Enter. Teammates replace stubs with real implementations later.
- **himpublic-ros**: ROS2 packages (sim, perception, fusion, autonomy, command center bridge). Not required for the Python pipeline.

---

## 2. himpublic-py: Always-on agent

### 2.1 Entrypoint and run

- **Entry**: `python -m himpublic.main` (from `himpublic-py/` with `pip install -e .` or `PYTHONPATH=src`).
- **Shutdown**: Ctrl+C or SIGINT/SIGTERM; tasks are cancelled, camera released, robot stopped.

**Typical commands**

```bash
# Terminal 1: command center
python scripts/run_command_center.py

# Terminal 2: agent (webcam or file)
python -m himpublic.main --io local --video webcam
python -m himpublic.main --io local --video file --video-path path/to.mp4
python -m himpublic.main --io local --video file --video-path path/to.mp4 --no-command-center
```

**CLI (main)**  
`--io` (local|robot|mock), `--video` (webcam|file|robot), `--webcam-index`, `--video-path`, `--command-center`, `--no-command-center`, `--yolo-model`, `--det-thresh`, `--ring-seconds`, `--ring-fps`, `--telemetry-hz`, `--llm-hz`, `--save-heartbeat-seconds`, `--start-phase`, `--log-level`.

### 2.2 Mission phases (himpublic-py)

Defined in `src/himpublic/orchestrator/phases.py`. Each phase has exit conditions so phases can be demoed or failed independently.

| Phase | Purpose | Exit |
|-------|---------|------|
| **BOOT** | Self-check: sensors (video, robot frame), optional mic/comms | ready or degraded → SEARCH_LOCALIZE |
| **SEARCH_LOCALIZE** | Patrol, call out, listen; human detection | confidence above threshold → APPROACH_CONFIRM |
| **APPROACH_CONFIRM** | Navigate to target, re-detect, confirm person | standoff → SCENE_SAFETY_TRIAGE |
| **SCENE_SAFETY_TRIAGE** | Hazard scan, choose viewpoints | safe enough → DEBRIS or INJURY |
| **DEBRIS_ASSESSMENT** | Rubble: movable vs not, push/clear or report | access improved or not movable → INJURY |
| **INJURY_DETECTION** | Injury classifier, structured report | report complete → ASSIST_COMMUNICATE |
| **ASSIST_COMMUNICATE** | Talk to victim, send report | report acknowledged → HANDOFF_ESCORT |
| **HANDOFF_ESCORT** | Multi-victim or escort | mission command → DONE |
| **DONE** | Terminal | — |

- **Start phase**: `--start-phase <phase>` skips boot and starts in that phase (e.g. `approach_confirm` for demos).
- **SharedState** holds `phase`, `phase_entered_at`, `boot_ready`, `degraded_mode`; policy and telemetry use phase.

### 2.3 Frame handling (no continuous disk write)

- **LatestFrameStore** (`perception/frame_store.py`): Thread-safe; latest BGR frame + latest `Observation`; `update(frame, obs)`, `get_latest()`.
- **RingBuffer** (same file): Configurable `ring_seconds` and `ring_fps`; stores `(timestamp, jpeg_bytes, observation_summary)`; `get_window(seconds_back)`, `get_keyframes(k, strategy="spread")`.
- **Policy**: Do not save every frame; only event-triggered keyframes (and optional heartbeat) are written under `data/snapshots/`.

### 2.4 Events and command center

- **EventType** (`orchestrator/events.py`): FOUND_PERSON, HEARD_RESPONSE, POSSIBLE_INJURY, OPERATOR_REQUEST, HEARTBEAT.
- **EventManager**: `emit(event_type, meta)` gets keyframes from RingBuffer, writes JPEGs to `data/snapshots/<timestamp>_<event>.jpg`, and posts JSON + snapshots via **CommandCenterClient**. HEARTBEAT snapshots throttled (e.g. every 30s).
- **CommandCenterClient** (`comms/command_center_client.py`): `post_event(payload)`, `post_snapshot(jpeg_bytes, filename, meta)`. Fails gracefully if server is down.
- **Command center server** (`comms/command_center_server.py`): FastAPI POST /event, POST /snapshot, GET /latest; snapshots under `./data/snapshots/`.

### 2.5 Two-layer brain

- **ReflexController** (`orchestrator/policy.py`): High rate (~10–20 Hz). From `Observation`: STOP if obstacle too close; ROTATE_LEFT/RIGHT to center person if offset > threshold. Deterministic, safety-focused.
- **LLMPolicy** (same file): Low rate (~1–2 Hz). Returns **Decision** (action, params, say, wait_for_response_s, mode, confidence). Stub is rules-based; structure matches `docs/system_prompt.md` for swapping in a real LLM.
- **Action** enum: STOP, ROTATE_LEFT, ROTATE_RIGHT, FORWARD_SLOW, BACK_UP, WAIT, ASK, SAY.
- **Observation** (`perception/types.py`): timestamp, state, persons, primary_person_center_offset ([-1,1]), confidence, obstacle_distance_m, scene_caption.

### 2.6 Perception and I/O

- **PersonDetector** (`perception/person_detector.py`): YOLO (ultralytics); `detect(frame)`, `observe(frame, state)` → Observation; primary_person_center_offset from largest bbox.
- **VideoSource** (`io/video_source.py`): WebcamVideoSource, FileVideoSource, RobotVideoSource (placeholder). `read()` → BGR or None, `release()`.
- **AudioIO** (`io/audio_io.py`): LocalAudioIO (speak = log+print, listen = stdin with timeout); RobotAudioIO (placeholder). ASK + WAIT_FOR_RESPONSE with timeout in agent.
- **RobotInterface** (`io/robot_interface.py`): Protocol (get_rgbd_frame, play_tts, listen_asr, set_velocity, stop). MockRobot, BoosterAdapter (skeleton), Ros2Bridge (placeholder).

### 2.7 Agent loop (orchestrator/agent.py)

Concurrent asyncio tasks until stop:

- **perception_task**: Read frame, YOLO → Observation, update LatestFrameStore + RingBuffer; emit FOUND_PERSON once when first confident person.
- **audio_task**: When decision has `wait_for_response_s`, call listen(timeout), store transcript, emit HEARD_RESPONSE.
- **policy_task**: At llm_hz, read observation + conversation_state, call LLMPolicy, set decision and phase.
- **actuation_task**: At ~10 Hz, apply ReflexController override then robot commands or LocalAudioIO (SAY/ASK).
- **telemetry_task**: At telemetry_hz, post JSON (phase, mode, num_persons, confidence, etc.) to command center.

Boot: optional self-check (video/robot frame), then phase = SEARCH_LOCALIZE (or `--start-phase`). Clean shutdown: cancel tasks, release camera, stop robot.

---

## 3. wizard_oz: Wizard-of-Oz demo pipeline

### 3.1 Purpose

Run the full mission flow **without a robot**: you use camera (+ optional mic) and key toggles to simulate detections. Every “robot” action is a **placeholder** that logs the call and can wait for Enter. Teammates replace the action layer (and optionally perception) with real implementations.

### 3.2 Entrypoint and run

```bash
cd wizard_oz
pip install -r requirements.txt
python -m src.main --show --typed-mic --manual
```

- **--show**: Webcam window with overlay (phase, last action, toggles).
- **--manual**: After each action, press Enter to simulate completion.
- **--no-show**: Headless (dummy frame if no camera).
- **--save-video**, **--max-steps** optional.

**Keys**: `h` human, `d` debris, `i` injury, `n` next phase, `q` quit.

### 3.3 Phases (wizard_oz)

`src/supervisor/phases.py`: SEARCH → APPROACH → DEBRIS_ASSESS → INJURY_SCAN → REPORT → DONE.

- **SEARCH**: Periodic `speak("Calling out...")`; if human detected (or key `h`) → set target, go to APPROACH.
- **APPROACH**: `navigate_to(target_pose)` once, then DEBRIS_ASSESS.
- **DEBRIS_ASSESS**: If debris (or key `d`) → `clear_debris("push")`; then INJURY_SCAN.
- **INJURY_SCAN**: `scan_injuries()` once, then REPORT.
- **REPORT**: Build report JSON, `send_report(report)`, write to `artifacts/reports/report_<timestamp>.json` and snapshot image, then DONE.

Timeouts fall back to SEARCH; **`n`** forces next phase.

### 3.4 Perception placeholders

- **detect_humans(frame)** → `list[Detection]`: key `h` → one fake detection (confidence 0.9, bearing/distance).
- **detect_debris(frame)** → `list[DebrisFinding]`: key `d` → one fake finding.
- **detect_injuries(frame)** → `list[InjuryFinding]`: key `i` → two fake findings.

Signatures are fixed so real detectors can be swapped in.

### 3.5 Action API (actions/)

- **ActionClient** (abstract): `navigate_to`, `explore_step`, `stop`, `speak`, `clear_debris`, `scan_injuries`, `send_report`; all return **ActionResult(success, details, simulated)**.
- **PlaceholderActionClient**: For each call: print `ACTION[name](args=..., reason=...)`, append one JSON line to `artifacts/action_calls.jsonl`, return success; if `MANUAL_CONFIRM_ACTIONS`, wait for Enter. `send_report` also writes the report to `artifacts/reports/report_<timestamp>.json`.

See **wizard_oz/docs/action_api.md** for full signatures and intended behavior.

### 3.6 State machine and main

- **StateMachine** (`supervisor/state_machine.py`): Holds RunContext (target_pose, phase_log, last_humans/debris/injuries, last_action). `tick(frame, t)` runs perception, phase logic, and actions; returns False when DONE or max_steps. `force_next_phase(t)` for key `n`.
- **main.py**: ~10 Hz loop; read frame (or dummy if headless), handle keys, save snapshot when entering REPORT, call `sm.tick(frame)`, draw overlay, optional video write. Camera only opened when `--show`.

### 3.7 Docs and test

- **docs/wizard_of_oz.md**: Approach; how to plug in real actions and perception.
- **docs/action_api.md**: Action signatures and expected behavior.
- **docs/demo_script.md**: 60–90 s demo: command and key order.
- **tests/test_smoke.py**: Headless run of StateMachine + PlaceholderActionClient with mock frames and toggles; asserts phase progression and that actions return success.

---

## 4. How the two stacks relate

| | himpublic-py | wizard_oz |
|---|--------------|-----------|
| **Use** | Always-on agent with real (or file) video and optional robot | Demo without robot; you simulate detections and action completion |
| **Perception** | YOLO person + Observation; future: injury/debris | Placeholder detectors driven by keys h/d/i |
| **Actions** | RobotInterface (velocity, TTS, ASR) + LocalAudioIO | ActionClient placeholders (log + JSONL + optional Enter) |
| **Phases** | Boot → Search → Approach → Scene safety → Debris → Injury → Assist → Handoff → Done | Search → Approach → Debris → Injury → Report → Done |
| **Output** | Command center (events + snapshots), telemetry at 1 Hz | artifacts/action_calls.jsonl, artifacts/reports/ |

- **WoZ** is for demos and for defining the **action interface** teammates will implement (navigate, speak, clear_debris, scan_injuries, send_report).
- **himpublic-py** is the production-style pipeline: continuous run, frame store, events, two-layer brain, phase-based mission, command center. Robot and LLM can be wired in later.

---

## 5. Quick reference: key files

**himpublic-py**

- `src/himpublic/main.py` — CLI, signal handling, run agent.
- `src/himpublic/orchestrator/agent.py` — Async tasks, boot, perception/audio/policy/actuation/telemetry.
- `src/himpublic/orchestrator/phases.py` — Phase enum and labels.
- `src/himpublic/orchestrator/policy.py` — ReflexController, LLMPolicy, Action, Decision.
- `src/himpublic/orchestrator/events.py` — EventType, EventManager.
- `src/himpublic/perception/frame_store.py` — LatestFrameStore, RingBuffer.
- `src/himpublic/perception/person_detector.py` — YOLO, observe(), primary_person_center_offset.
- `src/himpublic/comms/command_center_client.py` — CommandCenterClient.
- `scripts/run_command_center.py` — Start FastAPI server.

**wizard_oz**

- `src/main.py` — WoZ main loop, keys, overlay.
- `src/supervisor/state_machine.py` — StateMachine, RunContext, phase ticks.
- `src/actions/action_client.py` — ActionClient interface.
- `src/actions/placeholders.py` — PlaceholderActionClient, JSONL, report write.
- `src/perception/*_detector.py` — detect_humans, detect_debris, detect_injuries (placeholders + toggles).

---

## 6. Dependencies

- **himpublic-py**: ultralytics, opencv-python, fastapi, uvicorn, requests (see pyproject.toml / README).
- **wizard_oz**: opencv-python, numpy (see wizard_oz/requirements.txt).

No ROS required for either Python pipeline.

---

## 7. Next steps & walk-around readiness

### Is it ready to test by walking around?

**Yes, with the latest additions.** Use **himpublic-py** with webcam + preview + optional TTS:

```bash
cd himpublic-py
pip install -e .
# Optional: pip install pyttsx3  for audible "call out" and questions
python -m himpublic.main --io local --video webcam --show
# With TTS (hear the agent): add --tts
python -m himpublic.main --io local --video webcam --show --tts
```

- **--show** (default): Live preview window with phase, person count, and detection boxes. Press **q** in the window to quit.
- **--no-show**: No window (e.g. headless or when using a video file).
- **--tts**: Use text-to-speech for `speak()` when available (e.g. pyttsx3); otherwise only print.

**What to expect:** You walk in front of the camera; YOLO detects you → FOUND_PERSON event, phase moves to APPROACH_CONFIRM, then through the phase chain. You’ll see phase and “Persons: 1” (or more) on the overlay. No robot motion in local mode—only phase transitions, printed/logged speech, and optional TTS. For a quicker demo without waiting for detection, use a short video with people: `--video file --video-path <mp4>`.

### Recommended order to tackle next

1. **Walk-around test** — Run with webcam + `--show` (and optionally `--tts`). Confirm detection and phase transitions, then try with a video file.
2. **Command center** — Run `python scripts/run_command_center.py` in another terminal and watch events/snapshots at 1 Hz and on FOUND_PERSON.
3. **Wizard-of-Oz** — Use `wizard_oz` for a key-driven demo (h/d/i/n) and to validate the action API before wiring real hardware.
4. **Real LLM** — Replace the rules-based `LLMPolicy` in `orchestrator/policy.py` with an LLM call using `docs/system_prompt.md` and keep the same `Decision` shape.
5. **Robot / navigation** — When hardware is available, implement `ActionClient` (or RobotInterface) and plug in real `navigate_to`, `speak`, etc.
