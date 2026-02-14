# Architecture: Python Orchestrator-First

## Why Python-Orchestrator-First

We have shifted from a "ROS-first" to a "Python orchestrator-first" architecture for the TreeHacks robot project. The rationale:

1. **Local development**: Run the full pipeline on WSL/Ubuntu without robot hardware or ROS.
2. **Vendor flexibility**: Connect to the robot via direct vendor SDK calls (e.g., Booster SDK) or a thin ROS2 bridge only when the SDK forces it.
3. **Testability**: Mock I/O allows deterministic demos and unit tests.
4. **Simplicity**: Orchestrator logic stays in Python; ROS is an optional transport layer.

## Module Boundaries

| Module | Responsibility |
|--------|----------------|
| `orchestrator` | Main loop, state machine (SEARCH → APPROACH → ASSESS → REPORT), config |
| `io` | Robot interface (Protocol), MockRobot, BoosterAdapter, Ros2Bridge |
| `perception` | Person/rubble/injury detection (stubs, pluggable models) |
| `audio` | ASR, TTS, sound localization (stubs) |
| `comms` | Command center client (HTTP/FastAPI) |
| `utils` | Logging, helpers |

## Data Flow

```
                    ┌─────────────────────┐
                    │   Orchestrator      │
                    │   (agent.py)        │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
   ┌──────────┐         ┌──────────┐          ┌──────────┐
   │   IO     │         │Perception│          │  Comms   │
   │ (robot)  │         │ (stubs)  │          │ (client) │
   └────┬─────┘         └──────────┘          └────┬─────┘
        │                                              │
        ▼                                              ▼
   ┌──────────┐                                  Command Center
   │ MockRobot│                                  (HTTP / print)
   │ Booster  │
   │ Ros2Bridge│
   └──────────┘
```

- **SEARCH**: Robot.get_rgbd_frame → PersonDetector; Robot.play_tts, Robot.listen_asr; Robot.set_velocity (rotate)
- **APPROACH**: Robot.set_velocity (forward), then stop
- **ASSESS**: Robot.get_rgbd_frame → InjuryDetector, RubbleDetector → AssessmentReport
- **REPORT**: Comms.send_report(report) → Command center

## Where ROS Fits (Optional Bridge)

ROS2 is **not** required for the core orchestrator. It is an **optional adapter**:

- **When to add**: Only if the robot SDK (e.g., Booster) exposes I/O exclusively via ROS2 topics/services.
- **How**: Implement `Ros2Bridge(RobotInterface)` in `io/ros2_bridge.py`. The orchestrator calls the same `RobotInterface` methods; the bridge subscribes/publishes ROS2 under the hood.
- **Default**: Use `MockRobot` for demos and `BoosterAdapter` for direct SDK when available.

## Swapping MockRobot for BoosterAdapter

1. Set env: `HIMPUBLIC_ROBOT_ADAPTER=booster`
2. Implement `BoosterAdapter` in `io/booster_adapter.py` to satisfy `RobotInterface`:
   - `get_rgbd_frame()`, `get_imu()`, `play_tts()`, `listen_asr()`, `set_velocity()`, `stop()`
3. The orchestrator uses `_create_robot(config)` which returns the configured adapter. No changes to `agent.py` needed.

## Robot Integration Layer

### RobotInterface abstraction

`RobotInterface` (Protocol) defines the contract for all robot adapters. Implementations plug into the orchestrator without changing its logic:

- `MockRobot`: deterministic mock for local demos and tests
- `BoosterAdapter`: skeleton for real Booster SDK calls
- `Ros2Bridge`: optional, only if SDK requires ROS2

### MockRobot vs BoosterAdapter

| | MockRobot | BoosterAdapter |
|--|-----------|----------------|
| Use case | Dev, CI, demos without hardware | Real robot validation, production |
| Data | Fake frames, no-op TTS/ASR | Real camera, IMU, audio, motion |
| Status | Implemented | Skeleton with TODOs (SDK calls pending) |

### Why validate hardware control before CV

We implement a **robot I/O smoke test layer** before building CV/autonomy:

1. **Connectivity first**: Confirm network, auth, and basic SDK connectivity work.
2. **Control validation**: TTS, velocity, stop must succeed on hardware before trusting perception output.
3. **Fail fast**: Catch robot connection issues early; avoid debugging CV when the real problem is I/O.
4. **Smoke test**: `scripts/smoke_test_robot.py` exercises BoosterAdapter (TTS, velocity, stop) and runs without crashing even when SDK methods raise `NotImplementedError`.
