"""Orchestrator configuration - dataclasses, env vars, and CLI overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Load .env from himpublic-py and repo root (e.g. treehacks2026) so OPENAI_API_KEY etc. are set
def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # config.py lives in src/himpublic/orchestrator/ -> 4 levels up = himpublic-py
    base = Path(__file__).resolve().parent.parent.parent.parent
    load_dotenv(base / ".env")
    load_dotenv(base.parent / ".env")

_load_dotenv()


def _env(key: str, default: str) -> str:
    """Read env var with default."""
    return os.environ.get(key, default)


def load_config(
    *,
    io_mode: str | None = None,
    video_mode: str | None = None,
    webcam_index: int | None = None,
    video_path: str | None = None,
    command_center_url: str | None = None,
    no_command_center: bool | None = None,
    yolo_model: str | None = None,
    detection_threshold: float | None = None,
    post_interval_frames: int | None = None,
    ring_seconds: float | None = None,
    ring_fps: float | None = None,
    telemetry_hz: float | None = None,
    llm_hz: float | None = None,
    save_heartbeat_seconds: float | None = None,
    start_phase: str | None = None,
    show_preview: bool | None = None,
    use_tts: bool | None = None,
    use_mic: bool | None = None,
    log_level: str | None = None,
    llm_every_n_ticks: int | None = None,
    llm_stuck_seconds: float | None = None,
    openai_api_key: str | None = None,
    debug_decisions: bool | None = None,
) -> OrchestratorConfig:
    """Load config. CLI/args override env vars."""
    def _str(k: str, d: str, override: str | None) -> str:
        return override if override is not None else _env(k, d)

    def _int(k: str, d: int, override: int | None) -> int:
        v = override
        if v is not None:
            return v
        return int(_env(k, str(d)))

    def _float(k: str, d: float, override: float | None) -> float:
        v = override
        if v is not None:
            return v
        return float(_env(k, str(d)))

    url = _str("HIMPUBLIC_COMMAND_CENTER_URL", "http://127.0.0.1:8000", command_center_url)
    if no_command_center:
        url = ""

    return OrchestratorConfig(
        io_mode=_str("HIMPUBLIC_IO_MODE", "mock", io_mode),
        video_mode=_str("HIMPUBLIC_VIDEO_MODE", "webcam", video_mode),
        webcam_index=_int("HIMPUBLIC_WEBCAM_INDEX", 0, webcam_index),
        video_path=_str("HIMPUBLIC_VIDEO_PATH", "", video_path),
        command_center_url=url,
        robot_adapter=_env("HIMPUBLIC_ROBOT_ADAPTER", "mock"),
        mock_search_iterations_to_detect=_int("HIMPUBLIC_MOCK_SEARCH_ITERATIONS", 3, None),
        yolo_model=_str("HIMPUBLIC_YOLO_MODEL", "yolov8n.pt", yolo_model),
        detection_threshold=_float("HIMPUBLIC_DETECTION_THRESHOLD", 0.5, detection_threshold),
        post_interval_frames=_int("HIMPUBLIC_POST_INTERVAL_FRAMES", 30, post_interval_frames),
        ring_seconds=_float("HIMPUBLIC_RING_SECONDS", 10.0, ring_seconds),
        ring_fps=_float("HIMPUBLIC_RING_FPS", 2.0, ring_fps),
        telemetry_hz=_float("HIMPUBLIC_TELEMETRY_HZ", 1.0, telemetry_hz),
        llm_hz=_float("HIMPUBLIC_LLM_HZ", 1.0, llm_hz),
        save_heartbeat_seconds=_float("HIMPUBLIC_SAVE_HEARTBEAT_SECONDS", 30.0, save_heartbeat_seconds),
        start_phase=_str("HIMPUBLIC_START_PHASE", "", start_phase or "").strip() or None,
        show_preview=show_preview if show_preview is not None else (_env("HIMPUBLIC_SHOW_PREVIEW", "1") == "1"),
        use_tts=use_tts if use_tts is not None else (_env("HIMPUBLIC_USE_TTS", "1") == "1"),
        use_mic=use_mic if use_mic is not None else (_env("HIMPUBLIC_USE_MIC", "1") == "1"),
        log_level=_str("HIMPUBLIC_LOG_LEVEL", "INFO", log_level),
        llm_every_n_ticks=_int("HIMPUBLIC_LLM_EVERY_N_TICKS", 3, llm_every_n_ticks),
        llm_stuck_seconds=_float("HIMPUBLIC_LLM_STUCK_SECONDS", 5.0, llm_stuck_seconds),
        openai_api_key=_str("OPENAI_API_KEY", "", openai_api_key),
        debug_decisions=debug_decisions if debug_decisions is not None else (_env("HIMPUBLIC_DEBUG_DECISIONS", "0") == "1"),
    )


@dataclass(frozen=True)
class OrchestratorConfig:
    """Configuration for the orchestrator agent."""

    # IO mode: mock (MockRobot) | local (VideoSource + LocalAudioIO) | robot (placeholder)
    io_mode: str = "mock"

    # Video: webcam | file | robot
    video_mode: str = "webcam"

    # Webcam index (for video_mode=webcam)
    webcam_index: int = 0

    # Video file path (for video_mode=file)
    video_path: str = ""

    # Command center base URL (empty = no posting)
    command_center_url: str = ""

    # Robot adapter (for io_mode=robot, legacy)
    robot_adapter: str = "mock"

    # Mock: iterations before person detected
    mock_search_iterations_to_detect: int = 3

    # YOLO model path/name
    yolo_model: str = "yolov8n.pt"

    # Detection score threshold
    detection_threshold: float = 0.5

    # Post event/snapshot every N frames (legacy)
    post_interval_frames: int = 30

    # Ring buffer: max seconds to keep, sample rate (FPS) for stored frames
    ring_seconds: float = 10.0
    ring_fps: float = 2.0

    # Telemetry post rate (Hz); heartbeat snapshot interval (seconds)
    telemetry_hz: float = 1.0
    save_heartbeat_seconds: float = 30.0

    # LLM policy call rate (Hz)
    llm_hz: float = 1.0

    # Start in this phase (skip full boot). Empty = run boot then SEARCH_LOCALIZE. For demos: e.g. "approach_confirm"
    start_phase: str | None = None

    # Show live camera preview with phase/detection overlay (walk-around testing)
    show_preview: bool = True

    # Use TTS for speak() when available (pyttsx3); else print only
    use_tts: bool = True

    # Use microphone for listen() when speech_recognition available; else stdin (type + Enter)
    use_mic: bool = True

    # Log level
    log_level: str = "INFO"

    # LLM-assisted policy: call LLM every N policy ticks in SEARCH_LOCALIZE, or when stuck this many seconds
    llm_every_n_ticks: int = 3
    llm_stuck_seconds: float = 5.0
    # OpenAI API key (empty = skip LLM, use FSM only)
    openai_api_key: str = ""

    # Print each decision to terminal (camera + heard -> action/say/listen) for debugging
    debug_decisions: bool = False
