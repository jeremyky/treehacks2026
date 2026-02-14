# Adam Development

> **Note:** This repo was vibe coded - it's a collection of experiments with Adam, our Booster K1 humanoid robot. Code quality varies, things might break, and that's okay. We're learning as we go.

Development folder for Adam's sports skills and social media presence.

## Python Orchestrator (TreeHacks)

**Architecture:** Python-orchestrator-first (not ROS-first). No ROS. Always-on agent runs until you stop it (Ctrl+C). Use local camera/mic now; swap to robot I/O via `--io robot --video robot` later (placeholder).

### Always-on agent

The agent runs continuously until Ctrl+C:

- **Perception**: Reads from VideoSource (webcam or file), YOLO person detection, builds an observation summary (primary person center offset, confidence). Keeps latest frame + observation in memory and a **ring buffer** of the last N seconds at low FPS (e.g. 2 FPS). **We do not save every frame to disk.**
- **Event-triggered persistence**: On important events (FOUND_PERSON, HEARD_RESPONSE, POSSIBLE_INJURY, OPERATOR_REQUEST), the agent saves 1–5 keyframes from the ring buffer to `data/snapshots/` and posts them to the command center. Optional heartbeat snapshots (e.g. every 30s) are throttled.
- **Two-layer brain**: A **reflex** controller runs at ~10–20 Hz for safe low-level overrides (stop near obstacle, turn toward person). An **LLM policy** (stub rules-based for now) runs at ~1–2 Hz for high-level mode (SEARCH / APPROACH / ASSESS / REPORT) and discrete actions (STOP, ROTATE_*, FORWARD_SLOW, ASK, SAY, WAIT). See `docs/system_prompt.md` for the intended LLM JSON schema.
- **Audio**: LocalAudioIO: stdin listen + print speak. ASK + WAIT_FOR_RESPONSE mode with timeout is supported.
- **Telemetry**: Throttled JSON at 1 Hz to the command center; snapshots only on events (and optional heartbeat).

### Quickstart

```bash
cd himpublic-py
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Terminal 1: run command center server
python scripts/run_command_center.py

# Terminal 2: run agent (webcam or file); stop with Ctrl+C
python -m himpublic.main --io local --video webcam --webcam-index 0
# or with a video file (no webcam needed):
python -m himpublic.main --io local --video file --video-path path/to/video.mp4

# Disable command center posting
python -m himpublic.main --io local --video file --video-path test.mp4 --no-command-center

# Mock mode (no camera)
python -m himpublic.main --io mock
```

Or without install: `PYTHONPATH=src python -m himpublic.main --io local --video file --video-path <path>`

### Frame handling (no continuous disk writes)

- **LatestFrameStore**: Thread-safe; holds latest BGR frame and latest Observation.
- **RingBuffer**: Configurable `--ring-seconds` and `--ring-fps`; stores timestamp + JPEG bytes + observation summary. Frames are compressed to JPEG at moderate quality. Use `get_keyframes(k, strategy="spread")` for event snapshots.
- **Event snapshots**: On FOUND_PERSON, HEARD_RESPONSE, POSSIBLE_INJURY, OPERATOR_REQUEST (and optional HEARTBEAT), keyframes are saved under `data/snapshots/<timestamp>_<event>.jpg` and posted to the command center.

### Source abstraction

- **local now**: `--io local --video webcam` or `--video file --video-path <path>`
- **robot later**: `--io robot --video robot` (placeholder; shows helpful error)

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--io` | local | local, robot, mock |
| `--video` | webcam | webcam, file, robot |
| `--webcam-index` | 0 | Webcam device index |
| `--video-path` | | Required when `--video file` |
| `--command-center` | http://127.0.0.1:8000 | FastAPI base URL |
| `--no-command-center` | off | Disable posting to command center |
| `--yolo-model` | yolov8n.pt | YOLO model |
| `--det-thresh` | 0.5 | Person detection score threshold |
| `--ring-seconds` | 10 | Ring buffer window (seconds) |
| `--ring-fps` | 2 | Ring buffer sample rate (FPS) |
| `--telemetry-hz` | 1 | Telemetry post rate (Hz) |
| `--llm-hz` | 1 | LLM policy rate (Hz) |
| `--save-heartbeat-seconds` | 30 | Heartbeat snapshot interval (seconds) |
| `--post-interval-frames` | 30 | Legacy: post every N frames |
| `--log-level` | INFO | Log level |

### Command center (FastAPI)

- **POST /event**: JSON payload (event type, timestamp, mode, num_persons, snapshot_paths, etc.).
- **POST /snapshot**: JPEG upload (multipart).
- **GET /latest**: Returns last event and snapshot path.

Snapshots are written only on events (and optional heartbeat) to `./data/snapshots/`.

### Troubleshooting

**WSL webcam**: Webcam may not be accessible in WSL. Use file mode: `--video file --video-path path/to/recording.mp4`.

**Test with prerecorded mp4**:
```bash
python -m himpublic.main --io local --video file --video-path test.mp4
```

---

## What is this?

We're teaching a humanoid robot to have personality - react to sports, wave at people, dance, and generally be fun. This repo contains all our experiments, scripts, and learnings.

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/HIMRobotics/bordeaux.git
cd bordeaux
pip install -r code/requirements.txt
```

### 2. Set up API keys

You'll need API keys for voice features:

```bash
# Add to ~/.zshrc or ~/.bashrc
export ELEVENLABS_API_KEY='your-key-here'  # For realistic TTS
export OPENAI_API_KEY='your-key-here'      # For real-time voice chat
```

Get keys from:
- ElevenLabs: https://elevenlabs.io/app/settings/api-keys
- OpenAI: https://platform.openai.com/api-keys

### 3. Install Booster SDK (for robot control)

See `week1/plan.md` for full instructions, or:

```bash
cd legacy/sdk
sudo ./install.sh
pip install pybind11 pybind11-stubgen
mkdir -p build && cd build
cmake .. -DBUILD_PYTHON_BINDING=on
make && sudo make install
```

## Folder Structure

```
├── src/himpublic/    # Python orchestrator (TreeHacks)
│   ├── main.py       # Entrypoint: python -m himpublic.main
│   ├── orchestrator/ # Agent, state machine, config
│   ├── io/           # RobotInterface, MockRobot, adapters
│   ├── perception/   # Person/rubble/injury detectors (stubs)
│   ├── audio/        # ASR, TTS, sound localization (stubs)
│   ├── comms/        # Command center client
│   └── utils/        # Logging
├── docs/             # ARCHITECTURE.md, DEV_GUIDE.md, CHANGELOG.md
├── code/             # Python scripts (the good stuff)
├── assets/           # Audio files, motion data
├── legacy/           # SDK, utilities
├── week1/            # Setup guide + first experiments
├── week2/            # Reaction system build
└── week3/            # Content creation notes
```

## Quick Start

```bash
# Run command center (optional; for event/snapshot receipt)
python scripts/run_command_center.py

# Run orchestrator with webcam
python -m himpublic.main --io local --video webcam

# Run with video file
python -m himpublic.main --io local --video file --video-path test.mp4

# Mock mode (no camera)
python -m himpublic.main

# Test robot connection (legacy)
python code/test_connection.py

# Run the reaction system (legacy)
python code/adam_reacts.py

# Test voice generation
python code/voice_tts.py --generate
```

## Key Scripts

| Script | What it does |
|--------|--------------|
| `adam_reacts.py` | Main reaction system - press keys to trigger reactions |
| `realtime_voice.py` | Real-time voice conversation with Adam |
| `voice_tts.py` | Generate voice clips with ElevenLabs |
| `motion_capture.py` | Record and playback arm motions |
| `quick_test.py` | All-in-one test menu |

## The Goal

**Make Adam have personality.**

5 core reactions -> film -> post -> see what resonates -> iterate.

## Related Repos

- [booster_robotics_sdk](https://github.com/BoosterRobotics/booster_robotics_sdk) - Official Booster SDK
- [robocup_demo](https://github.com/BoosterRobotics/robocup_demo) - Soccer demos
- [GMR](https://github.com/YanjieZe/GMR) - Motion retargeting for custom dances

## Contributing

This is experimental code, but PRs are welcome! If something's broken, open an issue.

## License

MIT - see [LICENSE](LICENSE)
