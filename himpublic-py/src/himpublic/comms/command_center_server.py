"""Command center FastAPI server - receives events and snapshots."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

# Load .env so OPENAI_API_KEY is available (e.g. for /analyze-injuries)
def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # command_center_server.py lives in src/himpublic/comms/ -> 4 levels up = himpublic-py
    base = Path(__file__).resolve().parent.parent.parent.parent
    load_dotenv(base / ".env")
    load_dotenv(base.parent / ".env")

_load_dotenv()

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

logger = logging.getLogger(__name__)

app = FastAPI(title="HIM Public Command Center")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static"


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Return 204 to silence browser favicon requests."""
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """Serve bare-bones frontend."""
    html_path = _STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<p>Frontend not found. <a href='/latest'>/latest</a></p>")


@app.get("/snapshot/latest", response_model=None)
async def get_snapshot_latest() -> FileResponse | Response:
    """Return latest snapshot image, or 204 if none. No-store so feed updates continuously."""
    global _latest_snapshot_path
    if _latest_snapshot_path:
        p = Path(_latest_snapshot_path)
        if p.exists():
            return FileResponse(
                p,
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
    return Response(status_code=204)

# In-memory storage for latest event and incident report
_latest_event: dict[str, Any] | None = None
_latest_snapshot_path: str | None = None
_latest_report: dict[str, Any] | None = None
# Active robot display: status (spoken line) and stage (phase value), updated from heartbeat/robot_status
_robot_status: str = ""
_robot_stage: str = ""
_snapshots_dir: Path = Path("./data/snapshots")
_operator_messages: list[dict[str, Any]] = []
_comms: list[dict[str, Any]] = []  # { id, role: 'victim'|'robot'|'operator', text, timestamp }
_MAX_OPERATOR_MESSAGES = 100
_MAX_COMMS = 200
_comms_id = 0


def _ensure_snapshots_dir() -> Path:
    _snapshots_dir.mkdir(parents=True, exist_ok=True)
    return _snapshots_dir


def _append_comms(role: str, text: str) -> None:
    global _comms, _comms_id
    _comms_id += 1
    _comms.append({
        "id": _comms_id,
        "role": role,
        "text": (text or "").strip(),
        "timestamp": datetime.utcnow().isoformat(),
    })
    _comms = _comms[-_MAX_COMMS:]


@app.post("/event")
async def post_event(payload: dict[str, Any]) -> JSONResponse:
    """Accept JSON report payload. Store as latest event. Append to comms log for heard_response/robot_said."""
    global _latest_event, _comms, _robot_status, _robot_stage
    ev = payload.get("event") or ""
    if ev == "heard_response" and payload.get("transcript"):
        _append_comms("victim", payload["transcript"])
    if ev == "robot_said" and payload.get("text"):
        _append_comms("robot", payload["text"])
    if payload.get("status") is not None:
        _robot_status = str(payload.get("status", ""))
    if payload.get("stage") is not None:
        _robot_stage = str(payload.get("stage", ""))
    _latest_event = {**payload, "received_at": datetime.utcnow().isoformat()}
    logger.info("Event received: keys=%s", list(payload.keys()))
    return JSONResponse({"status": "ok", "received": True})


@app.post("/snapshot")
async def post_snapshot(
    file: UploadFile = File(...),
    metadata: str | None = Form(None),
) -> JSONResponse:
    """Accept multipart JPEG upload. Save with timestamp filename."""
    global _latest_snapshot_path
    dir_path = _ensure_snapshots_dir()
    now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ext = Path(file.filename or "snapshot.jpg").suffix or ".jpg"
    path = dir_path / f"snapshot_{now}{ext}"
    content = await file.read()
    path.write_bytes(content)
    _latest_snapshot_path = str(path)
    logger.info("Snapshot saved: %s (%d bytes)", path, len(content))
    return JSONResponse({
        "status": "ok",
        "path": _latest_snapshot_path,
        "metadata": metadata,
    })


@app.post("/report")
async def post_report(payload: dict[str, Any]) -> JSONResponse:
    """Accept incident report JSON (command center report pipeline)."""
    global _latest_report
    _latest_report = {**payload, "received_at": datetime.utcnow().isoformat()}
    logger.info("Report received: incident_id=%s", payload.get("incident_id"))
    return JSONResponse({"status": "ok", "received": True})


@app.get("/latest")
async def get_latest() -> JSONResponse:
    """Return last event, active robot status/stage, latest snapshot path, report, and comms."""
    return JSONResponse({
        "event": _latest_event,
        "status": _robot_status,
        "stage": _robot_stage,
        "snapshot_path": _latest_snapshot_path,
        "report": _latest_report,
        "comms": list(_comms),
    })


@app.post("/operator-message")
async def post_operator_message(payload: dict[str, Any]) -> JSONResponse:
    """Accept operator message from webapp. Robot will poll GET /operator-messages and speak it. Also append to comms."""
    global _operator_messages
    text = (payload.get("text") or "").strip()
    if text:
        _operator_messages.append({"text": text, "received_at": datetime.utcnow().isoformat()})
        _operator_messages = _operator_messages[-_MAX_OPERATOR_MESSAGES:]
        _append_comms("operator", text)
        logger.info("Operator message: %s", text[:80])
    return JSONResponse({"status": "ok", "received": True})


@app.get("/operator-messages")
async def get_operator_messages() -> JSONResponse:
    """Return recent operator messages (for Python/robot to poll and speak)."""
    return JSONResponse({"messages": list(_operator_messages)})


@app.post("/operator-messages/ack")
async def post_operator_messages_ack(payload: dict[str, Any]) -> JSONResponse:
    """Robot acks after speaking messages up to index N (optional; clears messages so they are not re-spoken)."""
    global _operator_messages
    after_index = payload.get("after_index", -1)
    if isinstance(after_index, int) and after_index >= 0:
        _operator_messages = _operator_messages[after_index + 1:]
    return JSONResponse({"status": "ok"})
