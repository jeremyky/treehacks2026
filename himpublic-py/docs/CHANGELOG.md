# Changelog

All notable changes to the TreeHacks himpublic-py project are documented here.

## 2026-02-14 (always-on agent, 2-layer brain, frame store)

### Always-on agent (runs until Ctrl+C)

- **Agent loop**: Orchestrator runs continuously with asyncio tasks until SIGINT/SIGTERM or Ctrl+C. Clean shutdown: cancel tasks, release camera, stop robot.
- **Concurrent tasks**: perception (read frame, YOLO, update store/ring), audio (stdin listen in WAIT_FOR_RESPONSE), policy (~1–2 Hz LLM stub), actuation (~10 Hz reflex + robot/audio), telemetry (1 Hz JSON to command center).
- **CLI**: `--io {local,robot,mock}`, `--video {webcam,file,robot}`, `--webcam-index`, `--video-path`, `--command-center`, `--no-command-center`, `--yolo-model`, `--det-thresh`, `--ring-seconds`, `--ring-fps`, `--telemetry-hz`, `--llm-hz`, `--save-heartbeat-seconds`, `--post-interval-frames`, `--log-level`. Defaults documented in README.

### Frame handling (in-memory + ring buffer, event-triggered persistence)

- **LatestFrameStore** (`src/himpublic/perception/frame_store.py`): Thread-safe; holds latest BGR frame and latest Observation; `update(frame, obs)`, `get_latest()`.
- **RingBuffer** (`frame_store.py`): Configurable max_seconds and fps_sample; `push(frame_bgr, obs)` compresses to JPEG; `get_window(seconds_back)`, `get_keyframes(k, strategy="spread")`.
- **Observation** (`src/himpublic/perception/types.py`): timestamp, state, persons, primary_person_center_offset ([-1,1]), confidence, obstacle_distance_m, scene_caption.
- **No continuous disk writes**: Frames are not saved every frame; only event-triggered keyframes (and optional heartbeat) are written to `data/snapshots/`.

### Event manager

- **EventType** (`src/himpublic/orchestrator/events.py`): FOUND_PERSON, HEARD_RESPONSE, POSSIBLE_INJURY, OPERATOR_REQUEST, HEARTBEAT.
- **EventManager**: `emit(event_type, meta)` fetches keyframes from RingBuffer, saves JPEGs to `data/snapshots/<timestamp>_<event>.jpg`, posts JSON + snapshots via CommandCenterClient. HEARTBEAT snapshots throttled (e.g. every 30s).

### Command center client

- **CommandCenterClient** (`src/himpublic/comms/command_center_client.py`): `post_event(payload)`, `post_snapshot(jpeg_bytes, filename, meta)`. Fails gracefully if server not running. Legacy `send_event`, `send_snapshot`, `send_report` kept.

### Two-layer brain (Reflex + LLM policy)

- **policy.py** (`src/himpublic/orchestrator/policy.py`): **Action** enum (STOP, ROTATE_LEFT, ROTATE_RIGHT, FORWARD_SLOW, BACK_UP, WAIT, ASK, SAY). **Decision** dataclass (action, params, say, wait_for_response_s, mode, confidence). **ReflexController**: fast override from Observation (STOP if obstacle close; turn toward person if offset > threshold). **LLMPolicy**: stub rules-based `decide(obs, conversation_state)` returning Decision; structured for easy swap to real LLM; JSON schema in `docs/system_prompt.md`.

### Perception

- **PersonDetector.observe()** (`src/himpublic/perception/person_detector.py`): Returns Observation (persons, primary_person_center_offset, confidence). **primary_person_center_offset**: normalized [-1,1] for largest person bbox.

### Audio

- **LocalAudioIO**: stdin listen + print speak. ASK + WAIT_FOR_RESPONSE mode with timeout supported in agent (audio_task listens when decision has wait_for_response_s).

### Config

- **OrchestratorConfig** (`src/himpublic/orchestrator/config.py`): Added ring_seconds, ring_fps, telemetry_hz, llm_hz, save_heartbeat_seconds. **load_config** accepts no_command_center to force command_center_url to empty.

### Documentation

- **README.md**: Always-on agent description, frame handling (no saving every frame), LatestFrameStore + RingBuffer + event snapshots, Reflex vs LLM policy, run commands (command center + agent from webcam/file), new CLI flags, WSL/file mode note.
- **docs/system_prompt.md**: Intended LLM prompt and JSON output format for policy.
- **docs/CHANGELOG.md**: This entry.

### Files touched/added

- `src/himpublic/main.py` – argparse + signal handling, run until Ctrl+C
- `src/himpublic/orchestrator/agent.py` – always-on asyncio tasks, SharedState, frame store, events, clean shutdown
- `src/himpublic/orchestrator/config.py` – ring_*, telemetry_hz, llm_hz, save_heartbeat_seconds, no_command_center
- `src/himpublic/orchestrator/events.py` – EventType, EventManager
- `src/himpublic/orchestrator/policy.py` – Action, Decision, ReflexController, LLMPolicy stub
- `src/himpublic/perception/types.py` – Observation dataclass
- `src/himpublic/perception/frame_store.py` – LatestFrameStore, RingBuffer
- `src/himpublic/perception/person_detector.py` – observe(), primary_person_center_offset
- `src/himpublic/comms/command_center_client.py` – CommandCenterClient class
- `docs/system_prompt.md` – new
- `README.md`, `docs/CHANGELOG.md` – updated

---

## 2026-02-14 (earlier)

### Local laptop I/O pipeline (camera + audio)

- **VideoSource abstraction** (`src/himpublic/io/video_source.py`):
  - `BaseVideoSource`, `WebcamVideoSource`, `FileVideoSource`, `RobotVideoSource` (placeholder)
  - `read()` returns BGR frame or None; `release()` for cleanup
- **AudioIO abstraction** (`src/himpublic/io/audio_io.py`):
  - `LocalAudioIO`: speak (log+print), listen (stdin fallback with select on Unix)
  - `RobotAudioIO` (placeholder)
- **Command center server** (`src/himpublic/comms/command_center_server.py`):
  - FastAPI: POST /event (JSON), POST /snapshot (JPEG), GET /latest
  - Snapshots saved to `./data/snapshots/` with timestamps
- **run_command_center.py** (`scripts/run_command_center.py`): uvicorn launcher
- **YOLO person detector** (`src/himpublic/perception/person_detector.py`):
  - `PersonDetector` with ultralytics YOLOv8, configurable model/threshold
  - `draw_boxes()` for visualization; `Detection` in `perception/types.py`
- **Orchestrator wiring**:
  - Agent accepts video_source + audio_io; posts events/snapshots every N frames
  - Config: io_mode, video_mode, webcam_index, video_path, command_center_url, yolo_model, detection_threshold, post_interval_frames
- **CLI flags** (`main.py`): `--io`, `--video`, `--webcam-index`, `--video-path`, `--command-center`, `--yolo-model`, `--detection-threshold`, `--post-interval-frames`
- **Dependencies**: ultralytics, opencv-python, fastapi, uvicorn, requests
- **README**: quickstart, flags, command center, troubleshooting (WSL webcam, prerecorded mp4)

### BoosterAdapter skeleton + smoke test

- **BoosterAdapter skeleton** (`src/himpublic/io/booster_adapter.py`):
  - Constructor: robot_ip, username, optional password/ssh_key_path
  - Logged connection attempt (no real connection yet)
  - All methods log clearly and raise `NotImplementedError` with TODO comments for SDK insertion
- **smoke_test_robot.py** (`scripts/smoke_test_robot.py`):
  - Instantiates BoosterAdapter with placeholder IP
  - Calls play_tts, set_velocity, sleep 2s, stop; wrapped in try/except
  - Runs without crashing (catches expected NotImplementedError)
- **Hardware validation milestone**: Robot I/O smoke test layer defined; validate connectivity before CV/autonomy

### Architecture shift: Python orchestrator-first

- **New folders/files**:
  - `src/himpublic/` – main package
  - `src/himpublic/main.py` – entrypoint
  - `src/himpublic/orchestrator/` – agent, state_machine, config
  - `src/himpublic/io/` – RobotInterface, MockRobot, BoosterAdapter (placeholder), Ros2Bridge (placeholder)
  - `src/himpublic/perception/` – person_detector, rubble_detector, injury_detector (stubs)
  - `src/himpublic/audio/` – asr, tts, sound_localization (stubs)
  - `src/himpublic/comms/` – command_center_client
  - `src/himpublic/utils/` – logging
  - `docs/ARCHITECTURE.md`, `docs/DEV_GUIDE.md`, `docs/CHANGELOG.md`
  - `pyproject.toml` – package config for editable install
  - `requirements.txt` – minimal deps (stdlib only)
  - `tests/` – minimal unit test scaffolding (`test_orchestrator.py`)

- **New interfaces**:
  - `RobotInterface` (Protocol): get_rgbd_frame, get_imu, play_tts, listen_asr, set_velocity, stop
  - `MockRobot`: deterministic mock for demos
  - `AssessmentReport`: dataclass for ASSESS output
  - `MissionState`, `MissionEvent`: state machine enums

- **Entrypoint**: `python -m himpublic.main` runs orchestrator demo

- **Doc additions**: ARCHITECTURE.md (module boundaries, data flow, ROS optional), DEV_GUIDE.md (venv, run, config, add adapter), CHANGELOG.md (this file)
