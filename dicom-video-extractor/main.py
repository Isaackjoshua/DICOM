"""Application entry point."""

import sys
import logging
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from src.utils.logging_setup import setup_logging
from src.utils.handlers import configure_handlers
from src.utils.ffmpeg_utils import probe_ffmpeg
from src.utils.exceptions import FFmpegNotFoundError
from src.ui.main_window import MainWindow


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    configure_handlers()

    app = QApplication(sys.argv)
    app.setApplicationName("DICOM Video Extractor")
    app.setOrganizationName("IsaackJoshua")

    # Apply a minimal dark stylesheet
    app.setStyleSheet(_DARK_STYLE)

    # Probe FFmpeg before showing the window
    ffmpeg_info = None
    try:
        ffmpeg_info = probe_ffmpeg()
    except FFmpegNotFoundError as exc:
        logger.warning("FFmpeg not found: %s", exc)

    window = MainWindow(ffmpeg_info=ffmpeg_info)
    window.show()

    sys.exit(app.exec())


_DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1a1b26;
    color: #cdd6f4;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QMenuBar { background: #16161e; }
QMenuBar::item:selected { background: #2d2f45; }
QMenu { background: #1e1e2e; border: 1px solid #333; }
QMenu::item:selected { background: #2d2f45; }
QPushButton {
    background: #2d2f45;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 4px 12px;
    color: #cdd6f4;
}
QPushButton:hover { background: #363854; }
QPushButton:pressed { background: #414368; }
QPushButton:disabled { color: #555; background: #1e1e2e; }
QTableWidget {
    background: #16161e;
    gridline-color: #2d2f45;
    border: 1px solid #333;
    alternate-background-color: #1a1b26;
}
QHeaderView::section {
    background: #24243e;
    padding: 4px;
    border: none;
    font-weight: bold;
}
QComboBox, QDoubleSpinBox, QLineEdit {
    background: #24243e;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 2px 6px;
    color: #cdd6f4;
}
QProgressBar {
    background: #16161e;
    border: 1px solid #333;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}
QProgressBar::chunk { background: #7aa2f7; border-radius: 3px; }
QGroupBox {
    border: 1px solid #333;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 4px;
}
QGroupBox::title { subcontrol-position: top left; padding: 0 4px; }
QSplitter::handle { background: #333; }
"""


if __name__ == "__main__":
    main()
