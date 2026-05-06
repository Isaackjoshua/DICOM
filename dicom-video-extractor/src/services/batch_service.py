"""
Batch processing queue — data model for multi-file conversion jobs.

The BatchQueue is the authoritative ordered list of jobs that the UI and
worker both read from.  Status updates happen via update_job().
"""

import itertools
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

from src.services.conversion_service import ConversionRequest, ConversionResult

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]

_id_counter = itertools.count(1)


@dataclass
class BatchJob:
    job_id: int
    request: ConversionRequest
    status: JobStatus = "queued"
    result: Optional[ConversionResult] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        return self.result.duration_seconds if self.result else None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("done", "failed", "cancelled")


@dataclass
class BatchStats:
    total: int = 0
    queued: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    cancelled: int = 0
    total_frames: int = 0
    total_duration_seconds: float = 0.0


class BatchQueue:
    """Thread-safe ordered queue of conversion jobs."""

    def __init__(self) -> None:
        self._jobs: list[BatchJob] = []

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add(self, request: ConversionRequest) -> BatchJob:
        job = BatchJob(job_id=next(_id_counter), request=request)
        self._jobs.append(job)
        logger.debug("Queued job #%d: '%s'", job.job_id, request.input_path.name)
        return job

    def remove_by_id(self, job_id: int) -> bool:
        for i, job in enumerate(self._jobs):
            if job.job_id == job_id:
                del self._jobs[i]
                return True
        return False

    def clear_completed(self) -> int:
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if not j.is_terminal]
        removed = before - len(self._jobs)
        logger.debug("Cleared %d completed jobs.", removed)
        return removed

    def clear_all(self) -> None:
        self._jobs.clear()

    def update_job(
        self,
        job_id: int,
        status: JobStatus,
        result: Optional[ConversionResult] = None,
    ) -> None:
        for job in self._jobs:
            if job.job_id == job_id:
                job.status = status
                if result is not None:
                    job.result = result
                return
        logger.warning("update_job: job_id=%d not found.", job_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_jobs(self) -> list[BatchJob]:
        return list(self._jobs)

    def pending_jobs(self) -> list[BatchJob]:
        return [j for j in self._jobs if j.status == "queued"]

    def get_by_path(self, input_path_str: str) -> Optional[BatchJob]:
        for job in self._jobs:
            if str(job.request.input_path) == input_path_str:
                return job
        return None

    def stats(self) -> BatchStats:
        s = BatchStats(total=len(self._jobs))
        for j in self._jobs:
            setattr(s, j.status, getattr(s, j.status) + 1)
            if j.result:
                s.total_frames += j.result.frames_written
                if j.result.duration_seconds:
                    s.total_duration_seconds += j.result.duration_seconds
        return s

    def __len__(self) -> int:
        return len(self._jobs)
