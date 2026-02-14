# Developer Guide

## Setup

### 1. Create venv

```bash
cd himpublic-py
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# or: .venv\Scripts\activate  # Windows
```

### 2. Install package (editable)

```bash
pip install -e .
```

## Run the Demo

```bash
# Option A: after pip install -e .
python -m himpublic.main

# Option B: without install (from repo root)
PYTHONPATH=src python -m himpublic.main
```

## Smoke Test (Robot I/O)

Validate BoosterAdapter structure before wiring SDK:

```bash
python scripts/smoke_test_robot.py
```

Expects `NotImplementedError` (SDK not wired yet). Script runs without crashing and logs all steps.

Expected output: state transitions (SEARCH → APPROACH → ASSESS → REPORT) in logs. The mock robot "detects" a person after 3 search iterations by default.

## Configuration

Env vars (optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `HIMPUBLIC_ROBOT_ADAPTER` | `mock` | `mock`, `booster`, or `ros2` |
| `HIMPUBLIC_MOCK_SEARCH_ITERATIONS` | `3` | Iterations before mock "person detected" |
| `HIMPUBLIC_COMMAND_CENTER_URL` | `` | HTTP endpoint for reports (empty = print only) |
| `HIMPUBLIC_LOG_LEVEL` | `INFO` | Logging level |

Example:

```bash
HIMPUBLIC_MOCK_SEARCH_ITERATIONS=5 HIMPUBLIC_LOG_LEVEL=DEBUG python -m himpublic.main
```

## Add a Real Robot Adapter

1. Add `io/booster_adapter.py` (or similar) implementing `RobotInterface`.
2. Map each method to SDK/ROS calls:
   - `get_rgbd_frame()` → camera subscriber or SDK call
   - `play_tts()` → TTS service or speaker
   - `listen_asr()` → ASR service or mic pipeline
   - `set_velocity(vx, wz)` → base velocity command
   - `stop()` → emergency stop
3. Set `HIMPUBLIC_ROBOT_ADAPTER=booster` (or add a new adapter key in `config.py`).
