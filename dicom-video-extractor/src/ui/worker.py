"""QThread-based conversion worker. No DICOM I/O on the GUI thread."""

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.services.batch_service import BatchJob, BatchQueue
from src.services.conversion_service import ConversionRequest, ConversionResult, convert


class ConversionWorker(QObject):
    progress = pyqtSignal(int, int)        # current_frame, total_frames
    log = pyqtSignal(str, str)             # message, level
    file_started = pyqtSignal(str)         # input_path — job just started
    file_done = pyqtSignal(str, bool)      # input_path, success
    finished = pyqtSignal()

    def __init__(
        self,
        queue: BatchQueue,
        ffmpeg_path: str,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._queue = queue
        self._ffmpeg = ffmpeg_path
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Cancel the current file AND all remaining queued files."""
        self._cancel.set()

    def run(self) -> None:
        pending = self._queue.pending_jobs()
        total_files = len(pending)

        for idx, job in enumerate(pending):
            if self._cancel.is_set():
                # Mark all remaining queued jobs as cancelled
                for remaining in pending[idx:]:
                    self._queue.update_job(remaining.job_id, "cancelled")
                    self.file_done.emit(str(remaining.request.input_path), False)
                self.log.emit(
                    f"Batch cancelled — {total_files - idx} file(s) skipped.", "WARNING"
                )
                break

            self._queue.update_job(job.job_id, "running")
            self.file_started.emit(str(job.request.input_path))
            self.log.emit(
                f"[{idx + 1}/{total_files}] Converting '{job.request.input_path.name}'…",
                "INFO",
            )

            result: ConversionResult = convert(
                request=job.request,
                ffmpeg_path=self._ffmpeg,
                progress_cb=lambda cur, tot: self.progress.emit(cur, tot),
                log_cb=lambda msg, level: self.log.emit(msg, level),
                cancel_event=self._cancel,
            )

            if self._cancel.is_set() and not result.success:
                self._queue.update_job(job.job_id, "cancelled", result)
            else:
                status = "done" if result.success else "failed"
                self._queue.update_job(job.job_id, status, result)

            self.file_done.emit(str(job.request.input_path), result.success)
            label = "OK" if result.success else f"FAILED: {result.error}"
            level = "INFO" if result.success else "ERROR"
            self.log.emit(f"'{job.request.input_path.name}' → {label}", level)

            # Do NOT clear the cancel event here — once cancelled, stop everything.

        self.finished.emit()


def make_worker_thread(worker: ConversionWorker) -> QThread:
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread
