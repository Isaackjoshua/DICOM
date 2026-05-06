"""Main application window."""

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.dicom_reader import DicomFileInfo, validate_and_load
from src.core.fps_resolver import FpsResult, resolve_fps
from src.services.conversion_service import ConversionRequest
from src.ui.metadata_dialog import MetadataDialog
from src.ui.widgets import DropZone, DualProgressBar, LogPanel
from src.ui.worker import ConversionWorker, make_worker_thread
from src.utils.exceptions import DicomValidationError, MissingPixelDataError
from src.utils.ffmpeg_utils import FFmpegInfo, get_install_instructions

logger = logging.getLogger(__name__)

FILE_COLUMNS = ["Name", "Modality", "Frames", "Transfer Syntax", "FPS", "Status"]
PRESETS = ["High", "Lossless", "Compressed"]
FORMATS = ["MP4", "AVI", "MKV"]


class MainWindow(QMainWindow):
    def __init__(self, ffmpeg_info: Optional[FFmpegInfo], parent=None):
        super().__init__(parent)
        self._ffmpeg_info = ffmpeg_info
        self._file_infos: dict[str, DicomFileInfo] = {}   # path_str → info
        self._fps_results: dict[str, FpsResult] = {}
        self._worker: Optional[ConversionWorker] = None
        self._thread: Optional[QThread] = None

        self.setWindowTitle("DICOM → Video Extractor")
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._build_menu()

        if ffmpeg_info is None:
            self._show_ffmpeg_missing()
        else:
            self._log(f"FFmpeg {ffmpeg_info.version} found at '{ffmpeg_info.path}'.", "INFO")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)

        # Drop zone + buttons
        top = QHBoxLayout()
        self._drop_zone = DropZone()
        self._drop_zone.files_dropped.connect(self._add_files)
        top.addWidget(self._drop_zone, stretch=3)

        btn_col = QVBoxLayout()
        self._btn_add = QPushButton("Add Files…")
        self._btn_add.clicked.connect(self._open_file_dialog)
        self._btn_clear = QPushButton("Clear")
        self._btn_clear.clicked.connect(self._clear_files)
        btn_col.addWidget(self._btn_add)
        btn_col.addWidget(self._btn_clear)
        btn_col.addStretch()
        top.addLayout(btn_col)
        root.addLayout(top)

        # Splitter: file table | details panel
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # File table
        self._table = QTableWidget(0, len(FILE_COLUMNS))
        self._table.setHorizontalHeaderLabels(FILE_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.selectionModel().selectionChanged.connect(self._on_selection)
        splitter.addWidget(self._table)

        # Details panel
        details = QGroupBox("Conversion Settings")
        details_layout = QVBoxLayout(details)
        details.setMinimumWidth(260)

        self._lbl_file = QLabel("No file selected.")
        self._lbl_file.setWordWrap(True)
        details_layout.addWidget(self._lbl_file)

        details_layout.addWidget(QLabel("FPS Override (0 = auto):"))
        self._fps_spin = QDoubleSpinBox()
        self._fps_spin.setRange(0.0, 1000.0)
        self._fps_spin.setDecimals(2)
        self._fps_spin.setSpecialValueText("Auto")
        details_layout.addWidget(self._fps_spin)

        details_layout.addWidget(QLabel("Output Format:"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(FORMATS)
        details_layout.addWidget(self._fmt_combo)

        details_layout.addWidget(QLabel("Quality Preset:"))
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(PRESETS)
        details_layout.addWidget(self._preset_combo)

        details_layout.addWidget(QLabel("Output Folder:"))
        out_row = QHBoxLayout()
        self._lbl_out = QLabel("Same as input")
        self._lbl_out.setWordWrap(True)
        out_row.addWidget(self._lbl_out, stretch=1)
        self._btn_out = QPushButton("…")
        self._btn_out.setFixedWidth(30)
        self._btn_out.clicked.connect(self._choose_output_dir)
        out_row.addWidget(self._btn_out)
        details_layout.addLayout(out_row)

        details_layout.addStretch()
        splitter.addWidget(details)
        splitter.setSizes([750, 300])
        root.addWidget(splitter, stretch=1)

        # Progress
        self._progress = DualProgressBar()
        root.addWidget(self._progress)

        # Log panel
        self._log_panel = LogPanel()
        self._log_panel.setMaximumHeight(180)
        root.addWidget(self._log_panel)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_convert = QPushButton("Convert")
        self._btn_convert.setDefault(True)
        self._btn_convert.setStyleSheet("font-weight:bold; padding: 6px 24px;")
        self._btn_convert.clicked.connect(self._start_conversion)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._cancel_conversion)
        btn_row.addWidget(self._btn_convert)
        btn_row.addWidget(self._btn_cancel)
        root.addLayout(btn_row)

        self._output_dir: Optional[Path] = None

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("Open Files…", self._open_file_dialog)
        file_menu.addAction("Open Folder…", self._open_folder_dialog)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction("View Metadata", self._view_metadata)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("About", self._show_about)
        help_menu.addAction("FFmpeg Status", self._show_ffmpeg_status)

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    def _open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open DICOM Files", "", "DICOM Files (*.dcm *.dicom);;All Files (*)"
        )
        if paths:
            self._add_files(paths)

    def _open_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open DICOM Folder")
        if folder:
            paths = [str(p) for p in Path(folder).rglob("*") if p.is_file()]
            self._add_files(paths)

    def _add_files(self, paths: list[str]) -> None:
        for path_str in paths:
            path = Path(path_str)
            if path_str in self._file_infos:
                continue  # already queued
            try:
                info = validate_and_load(path)
            except (DicomValidationError, MissingPixelDataError) as exc:
                self._log(f"Skipped '{path.name}': {exc}", "WARNING")
                continue

            # Resolve FPS (open dataset to read timing tags)
            try:
                import pydicom
                ds = pydicom.dcmread(path_str, stop_before_pixels=True)
                fps_result = resolve_fps(ds)
            except Exception:
                from src.core.fps_resolver import FpsResult, DEFAULT_FPS
                fps_result = FpsResult(fps=DEFAULT_FPS, source="default_fallback")

            self._file_infos[path_str] = info
            self._fps_results[path_str] = fps_result
            self._add_table_row(path_str, info, fps_result)
            for w in info.warnings:
                self._log(f"[{path.name}] {w}", "WARNING")

    def _add_table_row(self, path_str: str, info: DicomFileInfo, fps: FpsResult) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(info.path.name))
        self._table.setItem(row, 1, QTableWidgetItem(info.modality))
        self._table.setItem(row, 2, QTableWidgetItem(str(info.num_frames)))
        ts_display = f"{info.transfer_syntax_name} ({info.transfer_syntax_uid})"
        self._table.setItem(row, 3, QTableWidgetItem(ts_display))
        self._table.setItem(row, 4, QTableWidgetItem(f"{fps.fps:.2f} [{fps.source}]"))
        self._table.setItem(row, 5, QTableWidgetItem("Queued"))
        # Store the path in the row for retrieval
        self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, path_str)

    def _clear_files(self) -> None:
        self._table.setRowCount(0)
        self._file_infos.clear()
        self._fps_results.clear()

    def _choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self._output_dir = Path(folder)
            self._lbl_out.setText(str(self._output_dir))

    # ------------------------------------------------------------------
    # Details panel
    # ------------------------------------------------------------------

    def _on_selection(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._lbl_file.setText("No file selected.")
            return
        row = rows[0].row()
        item = self._table.item(row, 0)
        if not item:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        info = self._file_infos.get(path_str)
        fps = self._fps_results.get(path_str)
        if info:
            self._lbl_file.setText(
                f"{info.path.name}\n"
                f"{info.columns}×{info.rows}  {info.bits_stored}-bit  {info.photometric_interpretation}"
            )
        if fps:
            self._fps_spin.setValue(fps.fps)

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def _start_conversion(self) -> None:
        if not self._file_infos:
            QMessageBox.warning(self, "No Files", "Add at least one DICOM file first.")
            return
        if self._ffmpeg_info is None:
            self._show_ffmpeg_missing()
            return

        preset = self._preset_combo.currentText().lower()
        fmt = self._fmt_combo.currentText().lower()
        fps_override = self._fps_spin.value() if self._fps_spin.value() > 0 else None

        requests: list[ConversionRequest] = []
        for path_str, info in self._file_infos.items():
            out_dir = self._output_dir or info.path.parent
            out_path = out_dir / (info.path.stem + f".{fmt}")
            requests.append(ConversionRequest(
                input_path=info.path,
                output_path=out_path,
                preset=preset,
                fps_override=fps_override,
            ))

        self._progress.reset(len(requests))
        self._btn_convert.setEnabled(False)
        self._btn_cancel.setEnabled(True)

        self._worker = ConversionWorker(requests, self._ffmpeg_info.path)
        self._thread = make_worker_thread(self._worker)

        self._worker.progress.connect(self._progress.update_file_progress)
        self._worker.log.connect(self._log)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished.connect(self._on_finished)

        self._thread.start()

    def _cancel_conversion(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._log("Cancellation requested…", "WARNING")
            self._btn_cancel.setEnabled(False)

    def _on_file_done(self, path_str: str, success: bool) -> None:
        self._progress.file_complete()
        # Update status column
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == path_str:
                status_item = self._table.item(row, 5)
                if status_item:
                    status_item.setText("Done" if success else "Failed")
                break

    def _on_finished(self) -> None:
        self._btn_convert.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._log("All conversions complete.", "INFO")

    # ------------------------------------------------------------------
    # Menus / dialogs
    # ------------------------------------------------------------------

    def _view_metadata(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No Selection", "Select a file in the list first.")
            return
        row = rows[0].row()
        item = self._table.item(row, 0)
        if not item:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        dlg = MetadataDialog(Path(path_str), self)
        dlg.exec()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About DICOM → Video Extractor",
            "<b>DICOM → Video Extractor</b><br>"
            "Version 0.1.0<br><br>"
            "Extracts pixel data from multi-frame DICOM files and encodes "
            "standard video files via FFmpeg.<br><br>"
            "© 2026 Isaack Joshua",
        )

    def _show_ffmpeg_status(self) -> None:
        if self._ffmpeg_info:
            QMessageBox.information(
                self,
                "FFmpeg Status",
                f"FFmpeg is available.\n\nPath: {self._ffmpeg_info.path}\nVersion: {self._ffmpeg_info.version}",
            )
        else:
            self._show_ffmpeg_missing()

    def _show_ffmpeg_missing(self) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("FFmpeg Not Found")
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("FFmpeg was not found on your system.\n\nThe Convert button is disabled.")
        msg.setDetailedText(get_install_instructions())
        msg.exec()
        self._btn_convert.setEnabled(False)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, message: str, level: str = "INFO") -> None:
        self._log_panel.append_log(message, level)
        getattr(logger, level.lower(), logger.info)(message)
