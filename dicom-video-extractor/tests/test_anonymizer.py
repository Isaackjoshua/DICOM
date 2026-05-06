"""Tests for the DICOM anonymizer."""

import tempfile
from pathlib import Path

import pydicom
import pydicom.data
import pytest

from src.services.anonymizer import (
    anonymize_dataset,
    get_phi_summary,
    write_anonymized_copy,
)


def _load_ct() -> pydicom.Dataset:
    return pydicom.dcmread(pydicom.data.get_testdata_file("CT_small.dcm"))


def test_patient_name_replaced():
    ds = _load_ct()
    anon = anonymize_dataset(ds)
    assert str(anon.PatientName) == "ANONYMOUS"


def test_patient_id_set_to_given_id():
    ds = _load_ct()
    anon = anonymize_dataset(ds, patient_id="TEST-001")
    assert str(anon.PatientID) == "TEST-001"


def test_institution_name_replaced():
    ds = _load_ct()
    ds.InstitutionName = "Real Hospital"
    anon = anonymize_dataset(ds)
    assert str(anon.InstitutionName) == "ANONYMIZED"


def test_patient_birth_date_blanked():
    ds = _load_ct()
    ds.PatientBirthDate = "19800101"
    anon = anonymize_dataset(ds)
    assert anon.PatientBirthDate == ""


def test_sop_instance_uid_regenerated():
    ds = _load_ct()
    original_uid = str(ds.SOPInstanceUID)
    anon = anonymize_dataset(ds)
    assert str(anon.SOPInstanceUID) != original_uid


def test_pixel_data_preserved():
    ds = _load_ct()
    import numpy as np
    orig_pixels = ds.pixel_array.copy()
    anon = anonymize_dataset(ds)
    anon_pixels = anon.pixel_array
    np.testing.assert_array_equal(orig_pixels, anon_pixels)


def test_patient_identity_removed_tag():
    ds = _load_ct()
    anon = anonymize_dataset(ds)
    assert getattr(anon, "PatientIdentityRemoved", None) == "YES"


def test_write_anonymized_copy(tmp_path):
    src = Path(pydicom.data.get_testdata_file("CT_small.dcm"))
    dst = tmp_path / "anon_CT_small.dcm"
    write_anonymized_copy(src, dst)
    assert dst.exists()
    result_ds = pydicom.dcmread(str(dst))
    assert str(result_ds.PatientName) == "ANONYMOUS"


def test_get_phi_summary():
    ds = _load_ct()
    ds.PatientName = "John Doe"
    ds.InstitutionName = "Test Hospital"
    summary = get_phi_summary(ds)
    assert isinstance(summary, dict)
    # PatientName should appear in summary since it's set
    assert any("patient" in k.lower() or "Patient" in k for k in summary)


def test_anonymize_does_not_mutate_original():
    ds = _load_ct()
    original_name = str(ds.PatientName)
    anonymize_dataset(ds)
    assert str(ds.PatientName) == original_name
