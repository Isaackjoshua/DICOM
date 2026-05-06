"""Unit tests for the pixel pipeline."""

import numpy as np
import pydicom
import pytest

from src.core.pixel_pipeline import (
    VolumeScalars,
    build_volume_scalars,
    process_frame,
)


def _base_ds(**kwargs) -> pydicom.Dataset:
    ds = pydicom.Dataset()
    ds.BitsStored = 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    for k, v in kwargs.items():
        setattr(ds, k, v)
    return ds


def test_monochrome1_inversion():
    frame = np.array([[0, 128, 255]], dtype=np.uint8)
    ds = _base_ds(PhotometricInterpretation="MONOCHROME1")
    scalars = VolumeScalars(p_low=0, p_high=255, computed=True)
    result = process_frame(frame.copy(), ds, scalars)
    assert result[0, 0] == 255
    assert result[0, 2] == 0


def test_monochrome2_not_inverted():
    frame = np.array([[0, 128, 255]], dtype=np.uint8)
    ds = _base_ds()
    scalars = VolumeScalars(p_low=0, p_high=255, computed=True)
    result = process_frame(frame.copy(), ds, scalars)
    assert result[0, 0] == 0
    assert result[0, 2] == 255


def test_16bit_scaled_to_uint8():
    frame = np.zeros((4, 4), dtype=np.uint16)
    frame[0, 0] = 0
    frame[3, 3] = 4095
    ds = _base_ds(BitsStored=12, BitsAllocated=16)
    scalars = build_volume_scalars(frame, ds)
    result = process_frame(frame.copy(), ds, scalars)
    assert result.dtype == np.uint8
    assert result.max() <= 255


def test_brightness_stability_across_frames():
    """Same scalars must be reused — identical-content frames must produce identical output."""
    ds = _base_ds(BitsStored=16, BitsAllocated=16)
    frame = np.full((8, 8), 1000, dtype=np.uint16)
    scalars = build_volume_scalars(frame, ds)

    out1 = process_frame(frame.copy(), ds, scalars)
    out2 = process_frame(frame.copy(), ds, scalars)
    np.testing.assert_array_equal(out1, out2)


def test_rescale_applied():
    frame = np.ones((4, 4), dtype=np.uint8) * 100
    ds = _base_ds(RescaleSlope=2.0, RescaleIntercept=-100.0)
    scalars = VolumeScalars(p_low=0, p_high=255, computed=True)
    result = process_frame(frame.copy(), ds, scalars)
    assert result.dtype == np.uint8


def test_output_c_contiguous():
    frame = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    frame = np.asfortranarray(frame)
    ds = _base_ds()
    scalars = VolumeScalars(p_low=0, p_high=255, computed=True)
    result = process_frame(frame, ds, scalars)
    assert result.flags["C_CONTIGUOUS"]


def test_volume_scalars_from_window():
    frame = np.zeros((8, 8), dtype=np.uint16)
    ds = _base_ds(WindowCenter=128, WindowWidth=256, BitsStored=16)
    scalars = build_volume_scalars(frame, ds)
    assert scalars.used_windowing is True
    assert scalars.p_low == 0.0
    assert scalars.p_high == 256.0
