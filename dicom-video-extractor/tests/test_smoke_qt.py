"""pytest-qt smoke tests — verify the window opens and doesn't crash."""

from pathlib import Path

import pydicom.data
import pytest
from PyQt6.QtCore import Qt

from src.ui.main_window import MainWindow


@pytest.fixture
def main_window(qtbot):
    window = MainWindow(ffmpeg_info=None)
    qtbot.addWidget(window)
    window.show()
    return window


def test_window_opens(main_window):
    assert main_window.isVisible()


def test_window_title(main_window):
    assert "DICOM" in main_window.windowTitle()


def test_convert_button_disabled_without_ffmpeg(main_window):
    assert not main_window._btn_convert.isEnabled()


def test_add_files_via_drop(main_window, qtbot):
    from PyQt6.QtCore import QMimeData, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDropEvent

    path = str(pydicom.data.get_testdata_file("CT_small.dcm"))
    main_window._add_files([path])

    assert main_window._table.rowCount() == 1
    item = main_window._table.item(0, 0)
    assert item is not None
    assert "CT_small" in item.text()


def test_clear_button(main_window, qtbot):
    path = str(pydicom.data.get_testdata_file("CT_small.dcm"))
    main_window._add_files([path])
    assert main_window._table.rowCount() == 1

    main_window._clear_files()
    assert main_window._table.rowCount() == 0


def test_adding_invalid_file_does_not_crash(main_window, qtbot, tmp_path):
    bad = tmp_path / "not_a_dicom.dcm"
    bad.write_bytes(b"garbage data not dicom")
    main_window._add_files([str(bad)])
    assert main_window._table.rowCount() == 0


def test_duplicate_file_not_added_twice(main_window, qtbot):
    path = str(pydicom.data.get_testdata_file("CT_small.dcm"))
    main_window._add_files([path])
    main_window._add_files([path])
    assert main_window._table.rowCount() == 1


def test_metadata_dialog_no_selection_shows_info(main_window, qtbot, monkeypatch):
    shown = []
    monkeypatch.setattr(
        "src.ui.main_window.QMessageBox.information",
        lambda *a, **kw: shown.append(True),
    )
    main_window._view_metadata()
    assert shown
