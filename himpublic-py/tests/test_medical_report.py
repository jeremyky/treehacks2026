"""Tests for medical report schema, evidence log, and renderer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def test_medical_report_schema_imports():
    from himpublic.medical import MedicalReport, IncidentMeta, ReportConfig
    meta = IncidentMeta(
        report_id="r1",
        session_id="s1",
        timestamp_start=0.0,
        timestamp_end=1.0,
    )
    report = MedicalReport(meta=meta)
    assert report.meta.report_id == "r1"
    assert report.patient_summary is None


def test_evidence_log_add_and_list():
    from himpublic.evidence import EvidenceLog, add_evidence
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "evidence.jsonl"
        log = EvidenceLog(log_path)
        e1 = log.add_evidence(type="image", source="camera", file_path="a.jpg", summary="Scene")
        e2 = log.add_evidence(type="audio", source="mic", confidence=0.9, summary="Transcript")
        assert e1 == "E1"
        assert e2 == "E2"
        items = log.list_evidence()
        assert len(items) == 2
        assert items[0]["type"] == "image"
        assert items[1]["confidence"] == 0.9


def test_generate_medical_report_produces_md():
    from himpublic.reporting import generate_medical_report
    with tempfile.TemporaryDirectory() as tmp:
        session_ctx = {"session_id": "test_sess", "report_id": "test_r"}
        observations = {
            "location_estimate": "Test room",
            "consciousness": "responsive",
            "primary_concern": "Possible injury",
            "triage_category": "Delayed",
        }
        images = [{"file_path": "scene.jpg", "section": "scene_overview", "caption": "Overview"}]
        artifact_paths = {"sessions_base": str(Path(tmp) / "sessions"), "images_relative": "images"}
        md_path, pdf_path = generate_medical_report(
            session_ctx, observations, images,
            audio=None, model_outputs=None, artifact_paths=artifact_paths,
        )
        assert pdf_path is None
        assert md_path.endswith("medical_report.md")
        content = Path(md_path).read_text(encoding="utf-8")
        assert "Medical / SAR Incident Report" in content
        assert "Incident Meta" in content
        assert "Location & Access" in content
        assert "Patient Summary" in content
        assert "Evidence & Provenance" in content
        assert "Automated preliminary assessment" in content
        assert "test_sess" in content or "test_r" in content
