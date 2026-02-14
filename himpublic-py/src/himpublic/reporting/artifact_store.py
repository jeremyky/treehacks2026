"""Artifact store: session folder, report.json, report.md, images with stable image_ids."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .types import IncidentReport, ImageEvidence


def image_id_from_bytes(data: bytes) -> str:
    """Stable image_id from content hash (first 12 hex chars)."""
    return hashlib.sha256(data).hexdigest()[:12]


def report_to_dict(report: IncidentReport) -> dict[str, Any]:
    """Convert IncidentReport to dict with stable key order for JSON."""

    def _loc(d: Any) -> dict[str, Any] | None:
        if d is None:
            return None
        return {
            "frame": d.frame,
            "x": d.x,
            "y": d.y,
            "yaw": d.yaw,
            "floor": d.floor,
            "area_label": d.area_label,
            "confidence": d.confidence,
            "approach_path_status": d.approach_path_status,
            "nav_notes": d.nav_notes,
        }

    def _victim(d: Any) -> dict[str, Any] | None:
        if d is None:
            return None
        return {
            "victim_id": d.victim_id,
            "detection": {
                "confidence": d.detection.confidence,
                "method": d.detection.method,
                "bbox": list(d.detection.bbox) if d.detection.bbox else None,
            },
            "responsiveness": d.responsiveness,
            "breathing": d.breathing,
            "mobility": d.mobility,
        }

    def _hazards_debris(d: Any) -> dict[str, Any] | None:
        if d is None:
            return None
        return {
            "hazards": [{"type": h.type, "severity": h.severity, "confidence": h.confidence, "notes": h.notes} for h in d.hazards],
            "debris": [
                {"type": x.type, "movable": x.movable, "confidence": x.confidence, "pose": x.pose, "notes": x.notes}
                for x in d.debris
            ],
            "recommended_tools": d.recommended_tools,
        }

    def _injuries(items: list) -> list[dict[str, Any]]:
        return [
            {
                "type": i.type,
                "body_region": i.body_region,
                "severity": i.severity,
                "confidence": i.confidence,
                "evidence_image_ids": i.evidence_image_ids,
            }
            for i in items
        ]

    def _medical(d: Any) -> dict[str, Any] | None:
        if d is None:
            return None
        return {
            "questions_asked": [{"question": q.question, "timestamp": q.timestamp} for q in d.questions_asked],
            "answers": [{"answer": a.answer, "timestamp": a.timestamp} for a in d.answers],
            "chatbot_summary": d.chatbot_summary,
            "triage_priority": d.triage_priority,
            "triage_rationale": [{"claim": r.claim, "evidence": r.evidence} for r in d.triage_rationale],
            "overall_confidence": d.overall_confidence,
        }

    def _images(items: list) -> list[dict[str, Any]]:
        return [
            {"image_id": i.image_id, "kind": i.kind, "path": i.path, "timestamp": i.timestamp, "description": i.description}
            for i in items
        ]

    def _actions(d: Any) -> dict[str, Any] | None:
        if d is None:
            return None
        actions = getattr(d, "recommended_actions", None) or []
        return {"recommended_actions": [{"action": a.action, "priority": a.priority, "why": a.why} for a in actions]}

    def _comms(d: Any) -> dict[str, Any] | None:
        if d is None:
            return None
        return {"sent": d.sent, "endpoint": d.endpoint, "error": d.error}

    return {
        "incident_id": report.incident_id,
        "timestamp_start": report.timestamp_start,
        "timestamp_end": report.timestamp_end,
        "robot_id": report.robot_id,
        "operator": report.operator,
        "location": _loc(report.location),
        "victim": _victim(report.victim),
        "hazards_debris": _hazards_debris(report.hazards_debris),
        "injuries": _injuries(report.injuries),
        "medical_chatbot": _medical(report.medical_chatbot),
        "images": _images(report.images),
        "recommended_actions": _actions(report.recommended_actions) or {},
        "comms_status": _comms(report.comms_status),
    }


def save_report_json(report: IncidentReport, path: str | Path) -> None:
    """Write report as JSON with stable key order and pretty formatting."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d = report_to_dict(report)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, sort_keys=False)


class ArtifactStore:
    """Session folder: ./artifacts/sessions/<incident_id>/ with report.json, report.md, images/."""

    def __init__(self, base_dir: str | Path = "artifacts") -> None:
        self._base = Path(base_dir)
        self._sessions = self._base / "sessions"
        self._current_incident_id: str | None = None

    def session_dir(self, incident_id: str) -> Path:
        """Return path for session folder; create if needed."""
        d = self._sessions / incident_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def images_dir(self, incident_id: str) -> Path:
        """Return path for images subfolder."""
        d = self.session_dir(incident_id) / "images"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_report(self, report: IncidentReport, markdown_content: str | None = None) -> Path:
        """Save report.json and optionally report.md to session folder."""
        incident_id = report.incident_id
        session = self.session_dir(incident_id)
        save_report_json(report, session / "report.json")
        if markdown_content:
            (session / "report.md").write_text(markdown_content, encoding="utf-8")
        return session

    def save_image(self, incident_id: str, image_id: str, data: bytes, ext: str = "png") -> Path:
        """Save image bytes to images/<image_id>.<ext>. Returns path."""
        images_dir = self.images_dir(incident_id)
        path = images_dir / f"{image_id}.{ext}"
        path.write_bytes(data)
        return path
