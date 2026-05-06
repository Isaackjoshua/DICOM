"""Reusable UI widgets: drop zone, log panel, progress."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

LEVEL_COLORS = {
    "DEBUG":   "#888888",
    "INFO":    "#dddddd",
    "WARNING": "#f0ad4e",
    "ERROR":   "#e74c3c",
}


class DropZone(QFrame):
    """A labelled frame that accepts DICOM file drops."""

    files_dropped = pyqtSignal(list)  # list[str]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "DropZone { border: 2px dashed #555; border-radius: 6px; background: #1e1e2e; }"
            "DropZone:hover { border-color: #7aa2f7; }"
        )

        layout = QVBoxLayout(self)
        self._label = QLabel("Drop DICOM files here  —  or use  Add Files…")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #888; font-size: 13px;")
        layout.addWidget(self._label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(
                "DropZone { border: 2px dashed #7aa2f7; border-radius: 6px; background: #1e1e3e; }"
            )

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet(
            "DropZone { border: 2px dashed #555; border-radius: 6px; background: #1e1e2e; }"
            "DropZone:hover { border-color: #7aa2f7; }"
        )

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
        self.setStyleSheet(
            "DropZone { border: 2px dashed #555; border-radius: 6px; background: #1e1e2e; }"
            "DropZone:hover { border-color: #7aa2f7; }"
        )


class LogPanel(QPlainTextEdit):
    """Read-only log panel with colour-coded levels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setStyleSheet(
            "QPlainTextEdit { background: #0d0d14; color: #cdd6f4; "
            "font-family: monospace; font-size: 12px; border: 1px solid #333; }"
        )

    def append_log(self, message: str, level: str = "INFO") -> None:
        color = LEVEL_COLORS.get(level.upper(), LEVEL_COLORS["INFO"])
        html = f'<span style="color:{color}">[{level}] {_escape(message)}</span>'
        self.appendHtml(html)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class DualProgressBar(QWidget):
    """Two stacked progress bars: per-file and overall."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.file_bar = QProgressBar()
        self.file_bar.setTextVisible(True)
        self.file_bar.setFormat("Frame %v / %m")

        self.overall_bar = QProgressBar()
        self.overall_bar.setTextVisible(True)
        self.overall_bar.setFormat("File %v / %m")

        layout.addWidget(self.file_bar)
        layout.addWidget(self.overall_bar)

    def reset(self, total_files: int) -> None:
        self.file_bar.setValue(0)
        self.file_bar.setMaximum(1)
        self.overall_bar.setValue(0)
        self.overall_bar.setMaximum(max(total_files, 1))

    def update_file_progress(self, current: int, total: int) -> None:
        self.file_bar.setMaximum(total)
        self.file_bar.setValue(current)

    def file_complete(self) -> None:
        self.overall_bar.setValue(self.overall_bar.value() + 1)
        self.file_bar.setValue(self.file_bar.maximum())


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
    )
