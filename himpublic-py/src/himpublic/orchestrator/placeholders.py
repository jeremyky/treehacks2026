"""
Placeholder robot actions for triage flow: capture_image, send_to_command_center.
Replace with real implementations when wiring to hardware/API.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CAPTURE_COUNTER = 0


def capture_image(view: str) -> str:
    """
    Placeholder: simulate capturing an image from a view.
    Returns a stable image id (path or id string) for the report.
    Real impl: trigger camera, save to artifact store, return path/id.
    """
    global _CAPTURE_COUNTER
    _CAPTURE_COUNTER += 1
    # Simulate a short capture delay (non-blocking in real impl: queue capture)
    id_str = f"capture_{view}_{int(time.time() * 1000)}_{_CAPTURE_COUNTER}"
    logger.info("Placeholder capture_image(%s) -> %s", view, id_str)
    return id_str


def send_to_command_center(report: dict) -> None:
    """
    Placeholder: send structured report to command center.
    Real impl: POST to command center API or queue for comms.
    """
    logger.info("Placeholder send_to_command_center: keys=%s", list(report.keys()))
    # Optional: call real client if configured
    try:
        from himpublic.comms.command_center_client import send_incident_report
        url = __import__("os").environ.get("HIMPUBLIC_COMMAND_CENTER_URL", "").strip()
        if url:
            send_incident_report(report, endpoint_url=f"{url.rstrip('/')}/report")
    except Exception as e:
        logger.debug("Command center send skipped or failed: %s", e)
