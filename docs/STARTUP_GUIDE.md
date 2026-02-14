# Rescue Robot — Startup Guide

One-file guide: what to run, in what order, and how the pieces work together.

---

## Prerequisites

- **API key in `.env`** — The app always reads `OPENAI_API_KEY` from a `.env` file (no modal or env var needed at runtime). Create a `.env` in **`himpublic-py/`** or in the **repo root** (`treehacks2026/`) with:
  ```
  OPENAI_API_KEY=sk-proj-...
  ```
  Both the orchestrator and the command center load `.env` on startup (they look in `himpublic-py` then repo root).

- **Python 3.10+** with the orchestrator deps installed (from `himpublic-py/`):
  ```bash
  cd himpublic-py && pip install -e .
  ```
  Optional: `pip install -e ".[mic]"` for microphone (SpeechRecognition, PyAudio). For TTS: `pip install pyttsx3`. For LLM policy: `pip install openai` (key comes from `.env` above).

- **Node 18+** for the operator console:
  ```bash
  cd webapp && npm install
  ```

- **Webcam** (for perception). The orchestrator uses the default camera; use `--video file --video-path <path>` to use a video file instead.

---

## Commands to Run (3 terminals)

Run these in order. Keep all three running.

### Terminal 1: Command Center (API server)

From the **repo root** or **himpublic-py**:

```bash
cd himpublic-py
python scripts/run_command_center.py
```

Or with uvicorn directly:

```bash
cd himpublic-py
uvicorn himpublic.comms.command_center_server:app --host 127.0.0.1 --port 8000
```

- Listens on **http://127.0.0.1:8000**
- Serves: `/latest`, `/snapshot/latest`, `/event`, `/snapshot`, `/operator-message`, `/operator-messages`, etc.
- Leave this running.

---

### Terminal 2: Orchestrator (robot / agent)

From **himpublic-py** (so the package is importable):

```bash
cd himpublic-py
python -m himpublic.main --command-center http://127.0.0.1:8000
```

- Uses webcam (or `--video file --video-path <path>`), runs perception (YOLO), audio (mic + TTS), and policy.
- **Posts** telemetry and snapshots to the command center.
- **Polls** `/operator-messages` and speaks any new operator messages via TTS, then acks.
- Optional: set `OPENAI_API_KEY` (or use `--no-command-center` to run without the command center).

---

### Terminal 3: Operator Console (frontend)

From the **repo root**:

```bash
cd webapp
npm run dev
```

- Opens the Vite dev server (usually **http://localhost:5173**).
- Vite proxies `/api` to `http://127.0.0.1:8000`, so the app talks to the command center without CORS.
- Open **http://localhost:5173** in a browser.

---

## How It All Fits Together

1. **Command center** is the hub: it receives events and snapshots from the orchestrator and operator messages from the frontend, and exposes them via `/latest` and related endpoints.

2. **Orchestrator** (robot):
   - Sends **telemetry** (phase, num_persons, simulated map position) and **snapshots** (camera keyframes) to the command center.
   - When the mic picks up speech, it sends a **heard_response** event (shown as **VICTIM** in the console).
   - When it speaks (policy or operator-relayed), it sends a **robot_said** event (shown as **ROBOT 1**).
   - It periodically fetches **operator messages** from the command center and speaks them out loud, then acks so they are cleared.

3. **Operator console** (frontend):
   - **Polls** `/latest` every couple of seconds and shows:
     - **Comms**: victim / robot / operator messages (from the command center comms log).
     - **Robot feed**: latest snapshot image (`/snapshot/latest`).
     - **Map**: robot position from telemetry (`robot_map_x`, `robot_map_y`).
   - When you type or click a quick-reply and send, it **POSTs** to `/operator-message`; that text is added to the comms log and to the queue the orchestrator polls, so the **robot speaks it** and it appears as OPERATOR then ROBOT 1.

So: **comms** = what the robot heard (victim) and said (robot), plus what you sent (operator). **Robot feed** = same images the robot is posting. **Map** = simulated position from the orchestrator’s current phase.

---

## Quick Checks

- **Command center**: open http://127.0.0.1:8000/latest in a browser; you should get JSON (event, snapshot_path, report, comms).  
- **Frontend**: open http://localhost:5173; you should see the operator console; after the orchestrator is running, comms, robot feed, and map should update.  
- **Orchestrator**: ensure the command center URL matches (e.g. `http://127.0.0.1:8000`). If you run the command center on another host/port, pass `--command-center <url>` and set `VITE_COMMAND_CENTER_URL` in `webapp/.env` if the frontend is not proxying to it.

For full API and data-flow details, see **docs/ARCHITECTURE.md**.
