"""Tests for the streaming frame extractor."""

from pathlib import Path

import numpy as np
import pydicom
import pydicom.data
import pytest

from src.core.dicom_reader import validate_and_load, open_dataset
from src.core.frame_extractor import iter_frames
from src.utils.exceptions import UnsupportedTransferSyntaxError


def _frames_from_path(dcm_path: str) -> list[np.ndarray]:
    path = Path(dcm_path)
    info = validate_and_load(path)
    ds = open_dataset(path)
    return list(iter_frames(ds, ts_uid=info.transfer_syntax_uid))


def test_uncompressed_multiframe_rtdose():
    path = pydicom.data.get_testdata_file("rtdose.dcm")
    frames = _frames_from_path(path)
    assert len(frames) == 15
    for f in frames:
        assert f.dtype == np.uint8
        assert f.ndim == 2  # grayscale


def test_rle_multiframe_rgb():
    path = pydicom.data.get_testdata_file("SC_rgb_rle_2frame.dcm")
    frames = _frames_from_path(path)
    assert len(frames) == 2
    for f in frames:
        assert f.dtype == np.uint8
        assert f.ndim == 3
        assert f.shape[2] == 3  # RGB


def test_jpeg_ybr_422_multiframe():
    path = pydicom.data.get_testdata_file("examples_ybr_color.dcm")
    frames = _frames_from_path(path)
    assert len(frames) == 30
    for f in frames:
        assert f.dtype == np.uint8
        assert f.shape == (240, 320, 3)  # YBR→RGB, shape preserved


def test_frames_are_c_contiguous():
    path = pydicom.data.get_testdata_file("examples_ybr_color.dcm")
    frames = _frames_from_path(path)
    for f in frames:
        assert f.flags["C_CONTIGUOUS"]


def test_cancel_stops_iteration():
    import threading
    path = pydicom.data.get_testdata_file("examples_ybr_color.dcm")
    info = validate_and_load(Path(path))
    ds = open_dataset(Path(path))
    cancel = threading.Event()

    frames = []
    for frame in iter_frames(ds, ts_uid=info.transfer_syntax_uid, cancel_event=cancel):
        frames.append(frame)
        if len(frames) == 3:
            cancel.set()

    assert len(frames) <= 4  # stopped near the cancellation point


def test_passthrough_syntax_raises():
    """iter_frames must refuse passthrough syntaxes — those go through stream-copy."""
    import pydicom
    ds = pydicom.Dataset()
    ds.file_meta = pydicom.Dataset()
    with pytest.raises(UnsupportedTransferSyntaxError):
        list(iter_frames(ds, ts_uid="1.2.840.10008.1.2.4.102"))
