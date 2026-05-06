"""DICOM tag viewer dialog."""

from pathlib import Path

import pydicom
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

# Tags that may contain PHI — highlight them
PHI_KEYWORDS = frozenset({
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
    "PatientAddress", "PatientTelephoneNumbers", "OtherPatientIDs",
    "ReferringPhysicianName", "InstitutionName", "InstitutionAddress",
    "StationName", "OperatorsName", "PerformingPhysicianName",
    "RequestingPhysician", "AccessionNumber",
})


class MetadataDialog(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"DICOM Metadata — {path.name}")
        self.resize(800, 600)

        layout = QVBoxLayout(self)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter tags…")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Tag", "Keyword", "VR", "Value"])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load(path)

    def _load(self, path: Path) -> None:
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True)
        except Exception as exc:
            label = QLabel(f"Error reading metadata: {exc}")
            self.layout().insertWidget(0, label)
            return

        self._rows: list[tuple[str, str, str, str]] = []
        for elem in ds:
            tag_str = f"({elem.tag.group:04X},{elem.tag.element:04X})"
            kw = elem.keyword or ""
            vr = elem.VR or ""
            val = str(elem.value) if not hasattr(elem.value, "__iter__") or isinstance(elem.value, (str, bytes)) else repr(elem.value)
            val = val[:200]
            self._rows.append((tag_str, kw, vr, val))

        self._populate(self._rows)

    def _populate(self, rows: list[tuple]) -> None:
        self._table.setRowCount(len(rows))
        for r, (tag, kw, vr, val) in enumerate(rows):
            for c, text in enumerate((tag, kw, vr, val)):
                item = QTableWidgetItem(text)
                if kw in PHI_KEYWORDS:
                    item.setForeground(Qt.GlobalColor.yellow)
                self._table.setItem(r, c, item)

    def _filter(self, text: str) -> None:
        text = text.lower()
        filtered = [
            row for row in self._rows
            if any(text in col.lower() for col in row)
        ]
        self._populate(filtered)
