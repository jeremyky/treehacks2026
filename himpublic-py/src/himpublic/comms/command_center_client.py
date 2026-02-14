"""Command center client - FastAPI/HTTP. Class + legacy helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from himpublic.reporting.types import CommsStatus

logger = logging.getLogger(__name__)


class CommandCenterClient:
    """Client for posting events and snapshots to command center. Fails gracefully if server down."""

    def __init__(self, base_url: str | None, timeout: int = 5) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._timeout = timeout
        self._enabled = bool(self._base_url)
        self._last_event_error_log: float = 0.0
        self._last_snapshot_error_log: float = 0.0
        self._error_log_interval_s: float = 60.0

    def post_event(self, payload: dict[str, Any]) -> bool:
        """POST JSON to /event. Returns False if disabled or request fails."""
        if not self._enabled:
            return False
        url = f"{self._base_url}/event"
        try:
            resp = requests.post(url, json=payload, timeout=self._timeout)
            if resp.ok:
                logger.debug("Event posted: %s", resp.status_code)
            return resp.ok
        except Exception as e:
            import time as _t
            now = _t.monotonic()
            if now - self._last_event_error_log >= self._error_log_interval_s:
                logger.warning(
                    "Command center unreachable (post event). Run with --no-command-center or start server: %s",
                    e,
                )
                self._last_event_error_log = now
            return False

    def post_report(self, payload: dict[str, Any]) -> bool:
        """POST report JSON to /report. Returns False if disabled or request fails."""
        if not self._enabled:
            return False
        url = f"{self._base_url}/report"
        try:
            resp = requests.post(url, json=payload, timeout=self._timeout)
            if resp.ok:
                logger.info("Report posted to command center: %s", resp.status_code)
            return resp.ok
        except Exception as e:
            logger.warning("Command center post_report failed: %s", e)
            return False

    def get_operator_messages(self) -> list[dict[str, Any]]:
        """GET /operator-messages. Returns list of { text, received_at } for robot to speak."""
        if not self._enabled:
            return []
        try:
            resp = requests.get(f"{self._base_url}/operator-messages", timeout=self._timeout)
            if resp.ok:
                data = resp.json()
                return data.get("messages") or []
        except Exception:
            pass
        return []

    def ack_operator_messages(self, after_index: int) -> bool:
        """POST /operator-messages/ack so server clears messages up to after_index (robot has spoken them)."""
        if not self._enabled:
            return False
        try:
            resp = requests.post(
                f"{self._base_url}/operator-messages/ack",
                json={"after_index": after_index},
                timeout=self._timeout,
            )
            return resp.ok
        except Exception:
            return False

    def post_snapshot(
        self,
        jpeg_bytes: bytes,
        filename: str,
        meta: dict[str, Any] | None = None,
    ) -> bool:
        """POST JPEG to /snapshot. filename used for form name. Returns False if disabled or fails."""
        if not self._enabled:
            return False
        url = f"{self._base_url}/snapshot"
        try:
            files = {"file": (filename, jpeg_bytes, "image/jpeg")}
            data = {"metadata": json.dumps(meta or {})} if meta else {}
            resp = requests.post(url, files=files, data=data, timeout=self._timeout)
            if resp.ok:
                logger.debug("Snapshot posted: %s", resp.status_code)
            return resp.ok
        except Exception as e:
            import time as _t
            now = _t.monotonic()
            if now - self._last_snapshot_error_log >= self._error_log_interval_s:
                logger.warning("Command center unreachable (post snapshot): %s", e)
                self._last_snapshot_error_log = now
            return False


def send_event(base_url: str, event: dict[str, Any], timeout: int = 5) -> bool:
    """Legacy: POST event to /event."""
    return CommandCenterClient(base_url, timeout=timeout).post_event(event)


def send_snapshot(
    base_url: str,
    jpeg_bytes: bytes,
    metadata: dict[str, Any] | None = None,
    timeout: int = 5,
) -> bool:
    """Legacy: POST JPEG snapshot to /snapshot."""
    return CommandCenterClient(base_url, timeout=timeout).post_snapshot(
        jpeg_bytes, "snapshot.jpg", metadata
    )


def send_report(url: str, report: dict[str, Any]) -> bool:
    """Legacy: send report to command center. If url empty, log and return True."""
    payload = json.dumps(report, indent=2)
    if not url:
        logger.info("Command center (mock): report would be sent:\n%s", payload)
        return True
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info("Command center responded: %s", resp.status)
            return 200 <= resp.status < 300
    except Exception as e:
        logger.error("Command center request failed: %s", e)
        return False


def send_incident_report(
    report_json: dict[str, Any],
    endpoint_url: str | None = None,
    timeout: int = 5,
) -> CommsStatus:
    """
    Send incident report JSON to command center. If endpoint_url not provided,
    returns CommsStatus(sent=False, endpoint="") so report is still saved locally.
    """
    if not (endpoint_url or "").strip():
        return CommsStatus(sent=False, endpoint="", error=None)
    url = (endpoint_url or "").rstrip("/")
    if not url.endswith("/report"):
        url = f"{url}/report" if url else ""
    try:
        resp = requests.post(url, json=report_json, timeout=timeout)
        ok = resp.ok
        if ok:
            logger.info("Incident report sent: %s", resp.status_code)
        return CommsStatus(sent=ok, endpoint=url, error=None if ok else f"HTTP {resp.status_code}")
    except Exception as e:
        logger.error("Send report failed: %s", e)
        return CommsStatus(sent=False, endpoint=url, error=str(e))
