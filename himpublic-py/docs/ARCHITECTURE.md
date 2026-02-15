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

## LLM Planner–Executor Decision Making

A **Planner–Executor** architecture enables LLM-driven micro-decisions within each phase while the orchestrator remains the state machine and executor.

### Architecture

- **Planner (LLM)**: Receives a compact `WorldState` snapshot each tick and outputs a JSON plan: `intent`, `actions` (from allowed action space), `rationale`, `confidence`. Plan horizon is 1–5 actions; replan every tick after execution.
- **Executor (existing code)**: Validates each action against phase-allowed tools and bounds (clamp rotate/walk/listen). Dispatches via existing functions or placeholders. Updates state; planner runs again next tick.

### Modules

| Module | Responsibility |
|--------|----------------|
| `planner/schema.py` | WorldState dataclass, action space (ALLOWED_TOOLS), phase→allowed tools map |
| `planner/llm_planner.py` | `plan_next_actions(world_state)` – prompt, JSON parse, fallback to `wait(1.0)` on failure |
| `planner/executor.py` | `validate_plan()`, `dispatch_action()`, `plan_to_decision()` |

### WorldState

- `phase`, `tick`, `vision` (persons, rubble), `audio` (heard_voice, voice_angle_deg), `robot` (heading, last_action, constraints), `case_file` (triage state). JSON-serializable.

### Action Space (examples)

Navigation: `call_out`, `listen`, `rotate`, `walk_forward`, `scan_pan`, `wait`. Perception: `scan_vision`, `capture_image`, `analyze_images_vlm`. Interaction: `push_obstacle`, `approach_person`. Medical: `ask`, `update_case`, `generate_report`.

### Integration

- Config: `use_llm_planner: bool` (default False). Env: `HIMPUBLIC_USE_LLM_PLANNER=1`. CLI: `--use-llm-planner`.
- When enabled, policy loop builds WorldState, calls planner, validates, converts first action to Decision, and dispatches non-actuation tools (e.g. `push_obstacle`) via `dispatch_action`.
- Logging: `[PLANNER]` plan JSON, `[EXEC]` action results, `[STATE]` key observations.

### Test Harness

```bash
python -m himpublic.tools.test_planner --scenario search_no_person
python -m himpublic.tools.test_planner --scenario voice_at_30deg
python -m himpublic.tools.test_planner --scenario victim_bleeding_leg --use-llm  # requires OPENAI_API_KEY
```
