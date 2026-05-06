"""Unit tests for DICOM validation and reader."""

import tempfile
from pathlib import Path

import pydicom
import pydicom.data
import pytest

from src.core.dicom_reader import (
    get_transfer_syntax_name,
    validate_and_load,
    PASSTHROUGH_SYNTAXES,
)
from src.utils.exceptions import DicomValidationError, MissingPixelDataError


def test_get_transfer_syntax_name_known():
    name = get_transfer_syntax_name("1.2.840.10008.1.2.1")
    assert "Explicit" in name


def test_get_transfer_syntax_name_unknown():
    name = get_transfer_syntax_name("9.9.9.9.9")
    assert name  # should return something, not crash


def test_passthrough_syntaxes_not_empty():
    assert len(PASSTHROUGH_SYNTAXES) > 0
    # H.264 must be in there
    assert "1.2.840.10008.1.2.4.102" in PASSTHROUGH_SYNTAXES


def test_validate_invalid_file():
    with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
        f.write(b"NOT A DICOM FILE")
        path = Path(f.name)
    with pytest.raises(DicomValidationError):
        validate_and_load(path)


def test_validate_real_dicom():
    path = Path(pydicom.data.get_testdata_file("CT_small.dcm"))
    info = validate_and_load(path)
    assert info.modality in ("CT", "MR", "US", "UNKNOWN") or info.modality
    assert info.rows > 0
    assert info.columns > 0
    assert info.transfer_syntax_uid != ""
    assert info.transfer_syntax_name != ""
