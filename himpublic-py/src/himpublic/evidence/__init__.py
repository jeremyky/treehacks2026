"""Append-only evidence log for report provenance (Open Evidence style)."""

from .evidence_log import EvidenceLog, add_evidence, load_evidence_log

__all__ = ["EvidenceLog", "add_evidence", "load_evidence_log"]
