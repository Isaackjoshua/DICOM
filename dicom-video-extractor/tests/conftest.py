"""Shared fixtures for the test suite."""

import numpy as np
import pydicom
import pydicom.data
import pytest


@pytest.fixture(scope="session")
def multiframe_dcm_path():
    """Return path to a multi-frame DICOM from pydicom's test data."""
    # CT_small has multiple frames and is uncompressed
    return pydicom.data.get_testdata_file("CT_small.dcm")


@pytest.fixture(scope="session")
def jpeg_dcm_path():
    """JPEG-compressed DICOM from pydicom test data."""
    return pydicom.data.get_testdata_file("JPEG-lossy.dcm")


@pytest.fixture
def synthetic_ds():
    """Minimal in-memory Dataset for unit tests."""
    ds = pydicom.Dataset()
    ds.file_meta = pydicom.Dataset()
    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.5"
    ds.is_implicit_VR = False
    ds.is_little_endian = True

    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.NumberOfFrames = 4

    rng = np.random.default_rng(0)
    pixel_data = rng.integers(0, 256, (4 * 64 * 64,), dtype=np.uint8).tobytes()
    ds.PixelData = pixel_data

    return ds
