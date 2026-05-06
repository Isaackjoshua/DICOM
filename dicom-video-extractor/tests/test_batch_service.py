"""Tests for BatchQueue and BatchJob."""

from pathlib import Path

import pytest

from src.services.batch_service import BatchJob, BatchQueue, BatchStats
from src.services.conversion_service import ConversionRequest, ConversionResult


def _req(name: str = "test.dcm") -> ConversionRequest:
    return ConversionRequest(
        input_path=Path(f"/tmp/{name}"),
        output_path=Path(f"/tmp/{name.replace('.dcm', '.mp4')}"),
    )


def _result(success: bool = True, frames: int = 10) -> ConversionResult:
    return ConversionResult(
        input_path=Path("/tmp/test.dcm"),
        output_path=Path("/tmp/test.mp4"),
        success=success,
        frames_written=frames,
        started_at=1000.0,
        finished_at=1005.0,
    )


def test_add_job():
    q = BatchQueue()
    job = q.add(_req())
    assert job.status == "queued"
    assert len(q) == 1


def test_pending_jobs():
    q = BatchQueue()
    j1 = q.add(_req("a.dcm"))
    j2 = q.add(_req("b.dcm"))
    pending = q.pending_jobs()
    assert len(pending) == 2


def test_update_job_status():
    q = BatchQueue()
    job = q.add(_req())
    q.update_job(job.job_id, "running")
    assert q.all_jobs()[0].status == "running"


def test_update_job_with_result():
    q = BatchQueue()
    job = q.add(_req())
    r = _result()
    q.update_job(job.job_id, "done", r)
    updated = q.all_jobs()[0]
    assert updated.status == "done"
    assert updated.result is r


def test_clear_completed():
    q = BatchQueue()
    j1 = q.add(_req("a.dcm"))
    j2 = q.add(_req("b.dcm"))
    q.update_job(j1.job_id, "done", _result())
    removed = q.clear_completed()
    assert removed == 1
    assert len(q) == 1
    assert q.all_jobs()[0].job_id == j2.job_id


def test_remove_by_id():
    q = BatchQueue()
    j = q.add(_req())
    assert q.remove_by_id(j.job_id)
    assert len(q) == 0
    assert not q.remove_by_id(9999)


def test_stats():
    q = BatchQueue()
    j1 = q.add(_req("a.dcm"))
    j2 = q.add(_req("b.dcm"))
    j3 = q.add(_req("c.dcm"))
    q.update_job(j1.job_id, "done", _result(True, 15))
    q.update_job(j2.job_id, "failed", _result(False, 0))
    stats = q.stats()
    assert stats.total == 3
    assert stats.done == 1
    assert stats.failed == 1
    assert stats.queued == 1
    assert stats.total_frames == 15


def test_duration_on_job():
    q = BatchQueue()
    j = q.add(_req())
    q.update_job(j.job_id, "done", _result())
    assert q.all_jobs()[0].duration_seconds == pytest.approx(5.0)


def test_get_by_path():
    q = BatchQueue()
    req = _req("find_me.dcm")
    job = q.add(req)
    found = q.get_by_path(str(req.input_path))
    assert found is not None
    assert found.job_id == job.job_id


def test_is_terminal():
    q = BatchQueue()
    j = q.add(_req())
    assert not q.all_jobs()[0].is_terminal
    q.update_job(j.job_id, "done")
    assert q.all_jobs()[0].is_terminal


def test_clear_all():
    q = BatchQueue()
    q.add(_req("a.dcm"))
    q.add(_req("b.dcm"))
    q.clear_all()
    assert len(q) == 0
