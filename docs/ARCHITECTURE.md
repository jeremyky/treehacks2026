# Rescue Robot — Full-Stack Architecture

This document describes how the robot (orchestrator), command center server, and operator frontend connect end-to-end: comms (what the robot hears and says), robot feed (images), and map position.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Operator Console (React + Vite)                                             │
│  • Comms: victim / robot / operator messages                                 │
│  • Robot feed: latest snapshot image                                         │
│  • Map: robot position (simulated from phase)                                │
│  • Send message → robot speaks it (TTS)                                     │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                 │ HTTP (poll /latest, POST /operator-message)
                                 │ /api proxied to command center in dev
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Command Center (FastAPI)                                                    │
│  • POST /event         ← telemetry, heard_response, robot_said              │
│  • POST /snapshot      ← keyframe JPEGs from robot                           │
│  • POST /operator-message  ← operator text (robot will speak)                │
│  • GET  /latest        → event, snapshot_path, report, comms, robot pos    │
│  • GET  /snapshot/latest → latest JPEG                                       │
│  • GET  /operator-messages → for robot to poll and speak                    │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                 │ HTTP (POST event/snapshot, GET operator-messages)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Orchestrator (Python agent)                                                 │
│  • Perception: camera → YOLO → events + ring buffer → snapshots              │
│  • Audio: mic → ASR → transcript → POST event heard_response               │
│  • Policy: LLM → decision.say → TTS + POST event robot_said                  │
│  • Operator loop: poll GET /operator-messages → TTS → POST ack               │
│  • Telemetry: phase, num_persons, robot_map_x/y (simulated) → POST /event    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 1. Comms: What the Robot Hears and What We Say

### Roles

- **Victim** — What the robot heard (ASR transcript). The orchestrator posts this when the mic captures speech and it is emitted as `heard_response`.
- **Robot** — What the robot said (TTS). The orchestrator posts this when it speaks (policy `decision.say` or operator-relayed phrase).
- **Operator** — What the operator typed or selected in the command center. The frontend POSTs to `/operator-message`; the server appends to the comms log and to the operator-message queue.

### Flow

1. **Robot hears something**  
   - Agent: `_audio_loop` gets transcript → `EventManager.emit(HEARD_RESPONSE, { transcript })` → `POST /event` with `event: "heard_response", transcript: "..."`.  
   - Server: appends to `_comms` with `role: "victim"`.  
   - Frontend: polls `GET /latest`, gets `comms`; displays as VICTIM.

2. **Robot says something**  
   - Agent: `_actuation_loop` runs `_audio_io.speak(decision.say)` and `_cc_client.post_event({ event: "robot_said", text: decision.say })`.  
   - Server: appends to `_comms` with `role: "robot"`.  
   - Frontend: same poll; displays as ROBOT 1.

3. **Operator sends a message (robot says it)**  
   - Frontend: user types or clicks quick-reply → `POST /operator-message { text }` and shows message as OPERATOR.  
   - Server: appends to `_comms` with `role: "operator"` and appends to `_operator_messages`.  
   - Agent: `_operator_message_loop` polls `GET /operator-messages`, speaks each new message via TTS, then `POST /operator-messages/ack { after_index }` so the server can clear them.  
   - After the robot speaks, the agent can also post `robot_said` (optional; currently operator text is only in comms as operator; if you want “Robot 1” to echo it, the agent can post `robot_said` when speaking operator text).

So **comms in the UI correlate directly**: victim = what the robot heard, robot = what the robot said, operator = what the operator sent for the robot to say.

## 2. Robot Feed (Images)

- The orchestrator pushes **keyframe JPEGs** to the command center on events (e.g. `FOUND_PERSON`, `HEARD_RESPONSE`, and throttled `HEARTBEAT` via `EventManager.emit`). Each call posts to `POST /snapshot` and the server stores the file and sets `_latest_snapshot_path`.
- The frontend **robot feed** panel requests `GET /snapshot/latest` (with cache-bust query) on the same poll interval as `GET /latest`. So the image shown is the **same** latest snapshot the server has from the robot.
- **Correspondence**: The feed image is the latest snapshot uploaded by the robot (camera view at event time). No separate “image stream”;
  the feed is driven by the same snapshot pipeline the orchestrator uses for events.

## 3. Map Position (Simulated from Robot Movements)

- The map (floor plan) uses a fixed SVG with rooms and a **robot** marker. The robot’s position is **simulated** on the server/orchestrator side because we do not have real odometry in this setup.
- **Telemetry**: The agent’s `_telemetry_loop` posts to `POST /event` (heartbeat) and includes:
  - `robot_map_x`, `robot_map_y` — computed in `_update_simulated_position(phase, obs)`:
    - **search_localize**: robot “drifts” along the corridor (x increases, y slight variation).
    - **approach_confirm** / **assist_communicate**: robot moves toward victim at `(68, 58)`.
    - Other phases: small drift.
- The command center stores the latest event (including `robot_map_x`, `robot_map_y`) and returns it in `GET /latest`.
- The frontend reads `event.robot_map_x` and `event.robot_map_y` and passes them to the floor plan as `robotXY`. The map’s robot marker and path line use this position, so the **map reflects (simulated) robot movement** over time.

## 4. Command Center API Summary

| Method | Path | Who | Purpose |
|--------|------|-----|---------|
| POST | /event | Orchestrator | Telemetry (heartbeat with phase, num_persons, robot_map_x/y), heard_response (transcript), robot_said (text). |
| POST | /snapshot | Orchestrator | Upload keyframe JPEG; server sets latest snapshot path. |
| POST | /report | Orchestrator / scripts | Incident/triage report JSON. |
| POST | /operator-message | Frontend | Operator text; server appends to comms and operator queue. |
| GET | /latest | Frontend | Last event, snapshot_path, report, **comms** (victim/robot/operator), event includes robot_map_x/y. |
| GET | /snapshot/latest | Frontend | Latest JPEG (robot feed). |
| GET | /operator-messages | Orchestrator | Queue of operator messages for TTS. |
| POST | /operator-messages/ack | Orchestrator | Clear messages up to index after speaking. |

## 5. Running the Stack

1. **Command center** (default port 8000):
   ```bash
   cd himpublic-py && python -m uvicorn himpublic.comms.command_center_server:app --reload --host 0.0.0.0 --port 8000
   ```
   Or use `scripts/run_command_center.py` if it points to this app.

2. **Orchestrator** (with command center URL so it posts events and polls operator messages):
   ```bash
   cd himpublic-py && python -m himpublic.main --command-center http://127.0.0.1:8000
   ```

3. **Frontend** (Vite dev, proxies /api to command center):
   ```bash
   cd webapp && npm run dev
   ```
   Open http://localhost:5173. Comms, robot feed, and map position update from the same command center the orchestrator is talking to.

## 6. File / Module Reference

| Layer | Path | Role |
|-------|------|------|
| Frontend | `webapp/` | React + Vite; Tailwind; `api/client.ts` talks to command center; Chat, FloorPlan, RobotStatus. |
| Command center | `himpublic-py/src/himpublic/comms/command_center_server.py` | FastAPI: /event, /snapshot, /latest, /comms via latest, /operator-message, /operator-messages, ack. |
| Command center client | `himpublic-py/src/himpublic/comms/command_center_client.py` | post_event, post_snapshot, get_operator_messages, ack_operator_messages. |
| Orchestrator | `himpublic-py/src/himpublic/orchestrator/agent.py` | Perception, audio (ASR/TTS), policy, actuation (TTS + robot_said), _operator_message_loop, _telemetry_loop (with robot_map_x/y). |
| Events | `himpublic-py/src/himpublic/orchestrator/events.py` | EventManager: emit event + keyframes → post_event + post_snapshot. |

This is the full architecture for connecting the robot to the frontend: **comms** (hear/say/operator), **robot feed** (images), and **map position** (simulated from phase).
