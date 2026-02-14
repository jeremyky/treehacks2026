"""Event manager: emit events, save keyframes, post to command center."""

from __future__ import annotations

import logging
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from himpublic.comms.command_center_client import CommandCenterClient

if TYPE_CHECKING:
    from himpublic.perception.frame_store import RingBuffer

logger = logging.getLogger(__name__)


class EventType(Enum):
    FOUND_PERSON = "found_person"
    HEARD_RESPONSE = "heard_response"
    POSSIBLE_INJURY = "possible_injury"
    OPERATOR_REQUEST = "operator_request"
    HEARTBEAT = "heartbeat"


class EventManager:
    """Emit events: fetch keyframes from ring buffer, save to disk, post to command center."""

    def __init__(
        self,
        ring_buffer: RingBuffer,
        client: CommandCenterClient,
        snapshots_dir: str | Path = "data/snapshots",
        keyframe_seconds_back: float = 5.0,
        keyframe_count: int = 3,
        heartbeat_snapshot_interval_s: float = 30.0,
    ) -> None:
        self._ring_buffer = ring_buffer
        self._client = client
        self._snapshots_dir = Path(snapshots_dir)
        self._keyframe_seconds_back = keyframe_seconds_back
        self._keyframe_count = keyframe_count
        self._heartbeat_snapshot_interval_s = heartbeat_snapshot_interval_s
        self._last_heartbeat_snapshot_time: float = 0.0

    def _ensure_dir(self) -> Path:
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        return self._snapshots_dir

    def emit(self, event_type: EventType, meta: dict[str, Any]) -> None:
        """Fetch keyframes from ring buffer, save JPEGs, post event + snapshots. Throttle HEARTBEAT."""
        if event_type == EventType.HEARTBEAT:
            now = time.monotonic()
            if now - self._last_heartbeat_snapshot_time < self._heartbeat_snapshot_interval_s:
                # Still post JSON telemetry at 1 Hz; skip snapshot
                payload = {**meta, "event": event_type.value}
                self._client.post_event(payload)
                return
            self._last_heartbeat_snapshot_time = now

        keyframes = self._ring_buffer.get_keyframes(
            k=self._keyframe_count,
            seconds_back=self._keyframe_seconds_back,
            strategy="spread",
        )
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        prefix = f"{ts}_{event_type.value}"
        saved_paths: list[str] = []
        dir_path = self._ensure_dir()
        for i, entry in enumerate(keyframes):
            name = f"{prefix}_{i}.jpg"
            path = dir_path / name
            path.write_bytes(entry.jpeg_bytes)
            saved_paths.append(str(path))
            self._client.post_snapshot(entry.jpeg_bytes, name, {"event": event_type.value, **meta})

        payload = {
            "event": event_type.value,
            "timestamp": time.time(),
            "snapshot_paths": saved_paths,
            **meta,
        }
        self._client.post_event(payload)
        logger.info("Event emitted: %s (snapshots=%d)", event_type.value, len(saved_paths))
