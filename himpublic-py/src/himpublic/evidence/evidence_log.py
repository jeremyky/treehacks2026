"""
Append-only evidence log per session (JSONL). Every report claim can be traced to observations.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# Optional: use EvidenceItem from medical schema when building report
try:
    from himpublic.medical.report_schema import EvidenceItem
except ImportError:
    EvidenceItem = None  # type: ignore[misc, assignment]


def _next_id(log_path: Path) -> str:
    """Generate next evidence id E1, E2, ... based on existing lines."""
    if not log_path.exists():
        return "E1"
    n = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                eid = obj.get("id", "")
                if eid.startswith("E") and eid[1:].isdigit():
                    n = max(n, int(eid[1:]))
            except json.JSONDecodeError:
                continue
    return f"E{n + 1}"


class EvidenceLog:
    """
    Append-only evidence log (JSONL) per session.
    Use add_evidence() to append a record and get evidence_id.
    """

    def __init__(self, log_path: str | Path) -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def add_evidence(
        self,
        *,
        type: str,  # image | audio | text | model_output | operator_note
        source: str,
        timestamp: float | None = None,
        file_path: str = "",
        confidence: float = 0.0,
        summary: str = "",
        model_metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Append one evidence record and return its evidence_id (e.g. E1, E2, ...).
        """
        timestamp = timestamp if timestamp is not None else time.time()
        evidence_id = _next_id(self._path)
        record = {
            "id": evidence_id,
            "timestamp": timestamp,
            "type": type,
            "source": source,
            "file_path": file_path or "",
            "confidence": confidence,
            "summary": summary or "",
            "model_metadata": dict(model_metadata or {}),
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return evidence_id

    def list_evidence(self) -> list[dict[str, Any]]:
        """Load all evidence records from the log (order preserved)."""
        out: list[dict[str, Any]] = []
        if not self._path.exists():
            return out
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def to_evidence_items(self) -> list[Any]:
        """Return list of EvidenceItem (if medical schema available) for report provenance table."""
        rows = self.list_evidence()
        if EvidenceItem is None:
            return []
        return [
            EvidenceItem(
                evidence_id=r.get("id", ""),
                type=r.get("type", ""),
                timestamp=float(r.get("timestamp", 0)),
                source=r.get("source", ""),
                file_path=r.get("file_path", ""),
                confidence=float(r.get("confidence", 0)),
                summary=r.get("summary", ""),
                model_metadata=dict(r.get("model_metadata") or {}),
            )
            for r in rows
        ]

    @property
    def path(self) -> Path:
        return self._path


def add_evidence(
    log_path: str | Path,
    *,
    type: str,
    source: str,
    timestamp: float | None = None,
    file_path: str = "",
    confidence: float = 0.0,
    summary: str = "",
    model_metadata: dict[str, Any] | None = None,
) -> str:
    """
    Standalone helper: append one evidence record to log_path and return evidence_id.
    """
    log = EvidenceLog(log_path)
    return log.add_evidence(
        type=type,
        source=source,
        timestamp=timestamp,
        file_path=file_path,
        confidence=confidence,
        summary=summary,
        model_metadata=model_metadata,
    )


def load_evidence_log(log_path: str | Path) -> EvidenceLog:
    """Open an existing evidence log at log_path."""
    return EvidenceLog(log_path)
