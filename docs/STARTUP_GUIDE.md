# Rescue Robot — Startup Guide

One-file guide: what to run, in what order, and how the pieces work together.
Covers **both** local (webcam) mode and **robot** (Booster K1) mode.

---

## Prerequisites (All Modes)

- **API key in `.env`** — Create a `.env` in **`himpublic-py/`** or the **repo root** (`treehacks2026/`):
  ```
  OPENAI_API_KEY=sk-proj-...
  ```
  Both the orchestrator and command center load `.env` on startup.

- **Python with deps** — We use the conda `(base)` environment which has everything:
  ```bash
  conda activate base
  ```
  Required packages: `ultralytics`, `opencv-python`, `requests`, `fastapi`, `uvicorn`, `numpy`, `openai`, `pyttsx3`, `SpeechRecognition`.

- **Node 18+** for the operator console:
  ```bash
  cd webapp && npm install
  ```

---

## Mode A: Local (Webcam) — 3 Terminals

Use this mode for testing without the robot. Uses your laptop webcam + local mic/speaker.

### Terminal 1: Command Center

```bash
cd himpublic-py
PYTHONPATH=src python -m uvicorn himpublic.comms.command_center_server:app --host 127.0.0.1 --port 8000
```

### Terminal 2: Orchestrator

```bash
cd himpublic-py
PYTHONPATH=src python -m himpublic.main --io local --command-center http://127.0.0.1:8000
```

### Terminal 3: Webapp

```bash
cd webapp
npm run dev
```

Open **http://localhost:5173** (or whichever port Vite reports).

---

## Mode B: Robot (Booster K1) — 4 Terminals

Use this mode when SSH'd into the K1 robot. The laptop runs the orchestrator + webapp; the robot runs a bridge server.

### Network Setup

| Device | IP | Role |
|--------|-----|------|
| Laptop | `192.168.10.1` | Orchestrator, command center, webapp |
| K1 Robot | `192.168.10.102` | Bridge server (camera, mic, speaker) |

Connect via USB-C Ethernet. SSH password: `123456`.

### Terminal 1 (Robot SSH): Bridge Server

```bash
ssh booster@192.168.10.102
source /opt/ros/humble/setup.bash && python3 ~/server.py
```

**Expected output:**
```
INFO: Trying ROS2 camera on topic /StereoNetNode/rectified_image ...
INFO: ROS2 camera: first frame received from /StereoNetNode/rectified_image (544x448)
INFO: Camera backend: ROS2 (/StereoNetNode/rectified_image)
INFO: Motion DISABLED (safe read-only mode). Use --allow-motion to enable.
INFO: Uvicorn running on http://0.0.0.0:9090
```

**Verify from laptop:** `curl http://192.168.10.102:9090/health`

**IMPORTANT:**
- You MUST `source /opt/ros/humble/setup.bash` before starting the server, or the camera will fail.
- The `server.py` file lives at `~/server.py` on the robot. To update it after code changes:
  ```bash
  # FROM LAPTOP (not from SSH!)
  scp himpublic-py/src/robot_bridge/server.py booster@192.168.10.102:~/server.py
  ```

### Terminal 2 (Laptop): Command Center

```bash
cd himpublic-py
PYTHONPATH=src python -m uvicorn himpublic.comms.command_center_server:app --host 127.0.0.1 --port 8000
```

### Terminal 3 (Laptop): Orchestrator

```bash
cd himpublic-py
PYTHONPATH=src python -m himpublic.main \
  --io robot \
  --robot-bridge-url http://192.168.10.102:9090 \
  --command-center http://127.0.0.1:8000 \
  --no-show
```

`--no-show` disables the OpenCV preview window (view the feed in the webapp instead).

**What happens on startup:**
1. Connects to robot bridge (camera + audio)
2. Runs search phase: calls out "Where are you?", audio-scans, navigates toward sound
3. YOLO detects person -> transitions to approach/confirm
4. Policy loop (GPT-4o-mini) makes decisions: say, ask, rotate, wait
5. Telemetry loop pushes snapshots to command center at ~1 Hz

### Terminal 4 (Laptop): Webapp

```bash
cd webapp
npm run dev
```

Open **http://localhost:5173** (or the port Vite reports, often `:5174` if 5173 is busy).

---

## Deploying Bridge Server Updates

When you change `himpublic-py/src/robot_bridge/server.py`:

1. **From laptop:** `scp himpublic-py/src/robot_bridge/server.py booster@192.168.10.102:~/server.py`
2. **On robot SSH:** Ctrl+C the running server, then: `source /opt/ros/humble/setup.bash && python3 ~/server.py`

---

## Smoke Test (Robot Mode)

Before running the full pipeline, verify the bridge works:

```bash
cd himpublic-py
python3 scripts/smoke_test_robot.py --host 192.168.10.102
```

Tests (in order): health, state, 3 camera frames, TTS speak, 5s mic recording.
Artifacts saved to `missions/smoke_001/`.

---

## How It All Fits Together

```
Laptop                                             K1 Robot
-----------------------------------               --------------------------
                                     HTTP
 Orchestrator (Python)          <------------>     Bridge Server (FastAPI:9090)
   - RobotBridgeClient             :9090             - ROS2 Camera Subscriber
   - BridgeVideoSource                               - ALSA Mic (arecord)
   - BridgeAudioIO                                   - TTS (espeak -> paplay)
   - YOLO perception                                 - Booster SDK (motion)
   - LLM policy (GPT-4o-mini)

 Command Center (FastAPI:8000)
   - /event    (telemetry)
   - /snapshot (JPEG frames)
   - /operator-message

 Webapp (Vite:5173)
   - Polls /latest every 2s
   - Shows camera feed
   - Shows comms log
   - Operator sends messages
```

1. **Robot Bridge** abstracts all hardware (camera, mic, speaker, motion) behind HTTP endpoints. The laptop pipeline has **zero ROS2 dependencies**.

2. **Orchestrator** pulls frames from the bridge, runs YOLO, runs LLM policy, speaks through the bridge, and pushes telemetry to the command center.

3. **Command Center** is the hub: receives events/snapshots from the orchestrator, serves them to the webapp, and relays operator messages back to the orchestrator.

4. **Webapp** is a React dashboard: shows live camera feed, comms log, floor plan, robot status, and lets the operator send messages.

---

## CLI Reference

```
python -m himpublic.main [OPTIONS]

IO Mode:
  --io {local,robot,mock}       IO backend (default: local)
  --video {webcam,file,robot}   Video source (default: webcam)
  --webcam-index N              Webcam device index (default: 0)
  --video-path PATH             Video file (when --video file)
  --robot-bridge-url URL        Bridge server URL (default: http://192.168.10.102:9090)

Command Center:
  --command-center URL          Command center URL (default: http://127.0.0.1:8000)
  --no-command-center           Disable command center posting

Detection:
  --yolo-model PATH             YOLO model (default: yolov8n.pt)
  --det-thresh FLOAT            Detection threshold (default: 0.5)

Behavior:
  --show / --no-show            OpenCV preview window (default: show)
  --no-tts                      Disable text-to-speech
  --no-mic                      Disable microphone (use keyboard input)
  --start-phase PHASE           Skip boot, start at a phase (e.g. search_localize)
  --debug-decisions             Print LLM decisions to terminal

Rates:
  --telemetry-hz FLOAT          Telemetry post rate (default: 1.0)
  --llm-hz FLOAT                LLM policy rate (default: 1.0)
```

---

## Quick Checks

| Check | Command | Expected |
|-------|---------|----------|
| Bridge alive | `curl http://192.168.10.102:9090/health` | `{"status":"ok","camera_ok":true,...}` |
| Command center alive | `curl http://127.0.0.1:8000/latest` | `{"event":...,"snapshot_path":...}` |
| Snapshot flowing | `curl -s http://127.0.0.1:8000/latest \| python3 -c "import sys,json; print(json.load(sys.stdin)['snapshot_path'])"` | Non-null path after orchestrator starts |
| Webapp loads | Open `http://localhost:5173` | Dashboard with camera feed + comms |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bridge camera "no frame within 5s" | Forgot to `source /opt/ros/humble/setup.bash` before starting server |
| `espeak` hangs on robot | Fixed in server.py: uses `espeak --stdout \| paplay` (not bare espeak) |
| V4L2 "can't open camera" | Normal -- perception service holds the lock. Bridge uses ROS2 instead |
| `ModuleNotFoundError: cv2` on laptop | `conda activate base` or `pip install opencv-python` |
| Webapp shows no feed | Orchestrator not running, or wrong command center URL |
| `scp: No such file` | Run scp from **laptop**, not from SSH session |
| Port 5173 in use | Vite auto-picks next port (5174, etc.) -- check terminal output |

For detailed robot hardware notes, see **himpublic-py/docs/ROBOT_INTEGRATION.md**.
For architecture details, see **docs/ARCHITECTURE.md**.
