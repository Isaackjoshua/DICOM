"""QThread-based conversion worker. No DICOM I/O on the GUI thread."""

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.services.conversion_service import ConversionRequest, ConversionResult, convert


class ConversionWorker(QObject):
    progress = pyqtSignal(int, int)        # current_frame, total_frames
    log = pyqtSignal(str, str)             # message, level
    file_done = pyqtSignal(str, bool)      # path, success
    finished = pyqtSignal()

    def __init__(
        self,
        requests: list[ConversionRequest],
        ffmpeg_path: str,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._requests = requests
        self._ffmpeg = ffmpeg_path
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        total_files = len(self._requests)
        for idx, req in enumerate(self._requests):
            if self._cancel.is_set():
                self.log.emit(f"Batch cancelled at file {idx + 1}/{total_files}.", "WARNING")
                break

            self.log.emit(
                f"[{idx + 1}/{total_files}] Converting '{req.input_path.name}'…", "INFO"
            )
            self._cancel.clear()  # allow per-file cancellation reset

            result: ConversionResult = convert(
                request=req,
                ffmpeg_path=self._ffmpeg,
                progress_cb=lambda cur, tot: self.progress.emit(cur, tot),
                log_cb=lambda msg, level: self.log.emit(msg, level),
                cancel_event=self._cancel,
            )

            self.file_done.emit(str(req.input_path), result.success)
            status = "OK" if result.success else f"FAILED: {result.error}"
            self.log.emit(f"'{req.input_path.name}' → {status}", "INFO" if result.success else "ERROR")

        self.finished.emit()


def make_worker_thread(worker: ConversionWorker) -> QThread:
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread
