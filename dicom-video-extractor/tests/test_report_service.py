"""Tests for JSON and CSV report generation."""

import csv
import json
from pathlib import Path

import pytest

from src.services.batch_service import BatchJob, BatchQueue
from src.services.conversion_service import ConversionRequest, ConversionResult
from src.services.report_service import save_csv_report, save_json_report
from src.core.fps_resolver import FpsResult


def _make_completed_queue() -> BatchQueue:
    q = BatchQueue()
    for i in range(3):
        req = ConversionRequest(
            input_path=Path(f"/tmp/file_{i}.dcm"),
            output_path=Path(f"/tmp/file_{i}.mp4"),
            preset="high",
        )
        job = q.add(req)
        result = ConversionResult(
            input_path=req.input_path,
            output_path=req.output_path,
            success=(i != 2),  # last one fails
            frames_written=10 * (i + 1) if i != 2 else 0,
            fps_result=FpsResult(fps=30.0, source="CineRate"),
            warnings=["test warning"] if i == 1 else [],
            error="Encode failed" if i == 2 else None,
            started_at=1000.0 + i * 10,
            finished_at=1005.0 + i * 10,
        )
        status = "done" if i != 2 else "failed"
        q.update_job(job.job_id, status, result)
    return q


def test_json_report_created(tmp_path):
    q = _make_completed_queue()
    out = tmp_path / "report.json"
    save_json_report(q.all_jobs(), out)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "summary" in data
    assert "jobs" in data
    assert len(data["jobs"]) == 3


def test_json_report_summary_counts(tmp_path):
    q = _make_completed_queue()
    out = tmp_path / "report.json"
    save_json_report(q.all_jobs(), out)
    data = json.loads(out.read_text())
    summary = data["summary"]
    assert summary["total_jobs"] == 3
    assert summary["done"] == 2
    assert summary["failed"] == 1
    assert summary["total_frames_written"] == 10 + 20 + 0


def test_json_report_job_fields(tmp_path):
    q = _make_completed_queue()
    out = tmp_path / "report.json"
    save_json_report(q.all_jobs(), out)
    jobs = json.loads(out.read_text())["jobs"]
    for job in jobs:
        assert "job_id" in job
        assert "input_path" in job
        assert "output_path" in job
        assert "status" in job
        assert "frames_written" in job
        assert "fps" in job
        assert "started_at" in job


def test_csv_report_created(tmp_path):
    q = _make_completed_queue()
    out = tmp_path / "report.csv"
    save_csv_report(q.all_jobs(), out)
    assert out.exists()
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 3


def test_csv_report_has_required_columns(tmp_path):
    q = _make_completed_queue()
    out = tmp_path / "report.csv"
    save_csv_report(q.all_jobs(), out)
    reader = csv.DictReader(open(out))
    cols = reader.fieldnames or []
    for required in ("job_id", "status", "frames_written", "fps", "duration_seconds"):
        assert required in cols, f"Missing column: {required}"


def test_json_report_failed_job_has_error(tmp_path):
    q = _make_completed_queue()
    out = tmp_path / "report.json"
    save_json_report(q.all_jobs(), out)
    jobs = json.loads(out.read_text())["jobs"]
    failed = [j for j in jobs if j["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["error"] is not None


def test_report_timestamps_are_iso(tmp_path):
    q = _make_completed_queue()
    out = tmp_path / "report.json"
    save_json_report(q.all_jobs(), out)
    jobs = json.loads(out.read_text())["jobs"]
    for j in jobs:
        if j["started_at"]:
            assert "T" in j["started_at"]  # ISO 8601 format
