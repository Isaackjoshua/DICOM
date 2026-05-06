"""
DICOM anonymizer — removes / replaces PHI tags and rewrites UIDs.

Follows the DICOM standard Basic Application Level Confidentiality Profile
(PS 3.15, Annex E, Table E.1-1) for the most common clinical tags.
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

import pydicom
from pydicom.uid import generate_uid

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Tag → (keyword, replacement_value)
# replacement_value=None → tag is DELETED
# replacement_value="" → tag is BLANKED
# replacement_value=<string> → tag is REPLACED with that value
# -----------------------------------------------------------------------
_REPLACE: dict[tuple[int, int], str] = {
    (0x0010, 0x0010): "ANONYMOUS",             # PatientName
    (0x0010, 0x0040): "",                       # PatientSex
    (0x0010, 0x1010): "",                       # PatientAge
    (0x0010, 0x1020): "",                       # PatientSize
    (0x0010, 0x1030): "",                       # PatientWeight
    (0x0008, 0x0080): "ANONYMIZED",             # InstitutionName
    (0x0008, 0x0081): "",                       # InstitutionAddress
    (0x0008, 0x1040): "",                       # InstitutionalDepartmentName
    (0x0008, 0x0090): "",                       # ReferringPhysicianName
    (0x0008, 0x1048): "",                       # PhysiciansOfRecord
    (0x0008, 0x1050): "",                       # PerformingPhysicianName
    (0x0008, 0x1060): "",                       # NameOfPhysiciansReadingStudy
    (0x0008, 0x1070): "",                       # OperatorsName
    (0x0010, 0x1040): "",                       # PatientAddress
    (0x0010, 0x2154): "",                       # PatientTelephoneNumbers
    (0x0032, 0x1032): "",                       # RequestingPhysician
    (0x0032, 0x1060): "",                       # RequestedProcedureDescription
    (0x0040, 0x0006): "",                       # ScheduledPerformingPhysicianName
    (0x0040, 0x0244): "",                       # PerformedProcedureStepStartDate
    (0x0040, 0x0245): "",                       # PerformedProcedureStepStartTime
}

_DELETE: frozenset[tuple[int, int]] = frozenset({
    (0x0010, 0x1000),   # OtherPatientIDs
    (0x0010, 0x1001),   # OtherPatientNames
    (0x0010, 0x2297),   # ResponsiblePerson
    (0x0010, 0x2299),   # ResponsibleOrganization
    (0x0038, 0x0300),   # CurrentPatientLocation
    (0x0040, 0x0275),   # RequestAttributesSequence
    (0x0040, 0xA124),   # UID (in SR content)
    (0x4008, 0x0111),   # InterpretationApproverSequence
    (0x4008, 0x010C),   # PhysicianApprovingInterpretation
})

# Tags that are UIDs and should be regenerated (not deleted)
_REGEN_UID: frozenset[tuple[int, int]] = frozenset({
    (0x0008, 0x0018),   # SOPInstanceUID
    (0x0020, 0x000D),   # StudyInstanceUID
    (0x0020, 0x000E),   # SeriesInstanceUID
    (0x0008, 0x0014),   # InstanceCreatorUID
})

# Date tags to blank or shift (we blank them here)
_BLANK_DATE: frozenset[tuple[int, int]] = frozenset({
    (0x0010, 0x0030),   # PatientBirthDate
    (0x0008, 0x0020),   # StudyDate
    (0x0008, 0x0021),   # SeriesDate
    (0x0008, 0x0022),   # AcquisitionDate
    (0x0008, 0x0023),   # ContentDate
    (0x0008, 0x002A),   # AcquisitionDateTime
})

# AccessionNumber — hashed, not deleted (needed for de-identification tracking)
_HASH_TAG: frozenset[tuple[int, int]] = frozenset({
    (0x0008, 0x0050),   # AccessionNumber
    (0x0010, 0x0020),   # PatientID
})


def anonymize_dataset(
    ds: pydicom.Dataset,
    patient_id: str = "ANON",
    keep_private: bool = False,
) -> pydicom.Dataset:
    """
    Return a modified copy of `ds` with PHI removed.
    Does NOT modify pixel data.
    """
    import copy
    ds = copy.deepcopy(ds)

    # Remove private tags unless explicitly kept
    if not keep_private:
        ds.remove_private_tags()
        logger.debug("Private tags removed.")

    # Regenerate UIDs
    uid_map: dict[str, str] = {}
    for tag in _REGEN_UID:
        elem = ds.get(tag)
        if elem is not None:
            old = str(elem.value)
            new = uid_map.setdefault(old, generate_uid())
            elem.value = new

    # Replace
    for tag, value in _REPLACE.items():
        elem = ds.get(tag)
        if elem is not None:
            elem.value = value

    # Hash
    for tag in _HASH_TAG:
        elem = ds.get(tag)
        if elem is not None:
            raw = str(elem.value)
            if tag == (0x0010, 0x0020):
                # PatientID: use the supplied patient_id
                elem.value = patient_id
            else:
                hashed = hashlib.sha256(raw.encode()).hexdigest()[:16].upper()
                elem.value = hashed

    # Blank dates
    for tag in _BLANK_DATE:
        elem = ds.get(tag)
        if elem is not None:
            elem.value = ""

    # Delete
    for tag in _DELETE:
        if tag in ds:
            del ds[tag]

    # Stamp the dataset as anonymized
    try:
        ds.PatientIdentityRemoved = "YES"
        ds.DeidentificationMethod = "Basic Application Level Confidentiality Profile"
    except Exception:
        pass

    return ds


def write_anonymized_copy(
    src_path: Path,
    dst_path: Path,
    patient_id: str = "ANON",
    keep_private: bool = False,
) -> None:
    """
    Load `src_path`, anonymize, and save to `dst_path`.
    Pixel data is preserved unchanged.
    """
    logger.info("Anonymizing '%s' → '%s'", src_path.name, dst_path)
    ds = pydicom.dcmread(str(src_path))
    anon = anonymize_dataset(ds, patient_id=patient_id, keep_private=keep_private)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    anon.save_as(str(dst_path))
    logger.info("Anonymized copy saved to '%s'.", dst_path)


def get_phi_summary(ds: pydicom.Dataset) -> dict[str, str]:
    """Return a dict of tag keyword → value for all PHI tags present in `ds`."""
    all_phi_tags = (
        set(_REPLACE) | set(_HASH_TAG) | _BLANK_DATE | _DELETE | _REGEN_UID
    )
    result = {}
    for tag in sorted(all_phi_tags):
        elem = ds.get(tag)
        if elem is not None:
            kw = pydicom.datadict.keyword_for_tag(tag) or f"({tag[0]:04X},{tag[1]:04X})"
            val = str(elem.value)
            if val:
                result[kw] = val
    return result
