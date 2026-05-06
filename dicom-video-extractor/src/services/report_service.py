"""
Per-job processing report — JSON and CSV output.
"""

import csv
import datetime
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.batch_service import BatchJob

logger = logging.getLogger(__name__)


def _job_to_dict(job: "BatchJob") -> dict:
    r = job.result
    fps = r.fps_result.fps if (r and r.fps_result) else None
    fps_source = r.fps_result.source if (r and r.fps_result) else None
    return {
        "job_id": job.job_id,
        "input_path": str(job.request.input_path),
        "output_path": str(job.request.output_path),
        "preset": job.request.preset,
        "status": job.status,
        "success": r.success if r else False,
        "frames_written": r.frames_written if r else 0,
        "fps": fps,
        "fps_source": fps_source,
        "duration_seconds": job.duration_seconds,
        "started_at": _fmt_epoch(r.started_at if r else None),
        "finished_at": _fmt_epoch(r.finished_at if r else None),
        "warnings": r.warnings if r else [],
        "error": r.error if r else None,
    }


def _fmt_epoch(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


def _build_summary(jobs: list["BatchJob"]) -> dict:
    total = len(jobs)
    done = sum(1 for j in jobs if j.status == "done")
    failed = sum(1 for j in jobs if j.status == "failed")
    cancelled = sum(1 for j in jobs if j.status == "cancelled")
    total_frames = sum(
        (j.result.frames_written if j.result else 0) for j in jobs
    )
    durations = [j.duration_seconds for j in jobs if j.duration_seconds is not None]
    total_duration = sum(durations)
    return {
        "total_jobs": total,
        "done": done,
        "failed": failed,
        "cancelled": cancelled,
        "total_frames_written": total_frames,
        "total_duration_seconds": round(total_duration, 2),
        "generated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
    }


def save_json_report(jobs: list["BatchJob"], output_path: Path) -> None:
    """Write a JSON report to *output_path*."""
    report = {
        "summary": _build_summary(jobs),
        "jobs": [_job_to_dict(j) for j in jobs],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("JSON report saved to '%s'.", output_path)


def save_csv_report(jobs: list["BatchJob"], output_path: Path) -> None:
    """Write a CSV report to *output_path*."""
    fieldnames = [
        "job_id", "input_path", "output_path", "preset", "status",
        "success", "frames_written", "fps", "fps_source",
        "duration_seconds", "started_at", "finished_at", "error",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            row = _job_to_dict(job)
            row["error"] = (row["error"] or "").replace("\n", " ")
            writer.writerow(row)
    logger.info("CSV report saved to '%s'.", output_path)
