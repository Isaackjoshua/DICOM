"""DICOM file validation, dataset loading, and transfer syntax detection."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.uid import UID

from src.utils.exceptions import DicomValidationError, MissingPixelDataError

logger = logging.getLogger(__name__)

# UID → human-readable name (subset; pydicom also has uid_dict)
TRANSFER_SYNTAX_NAMES: dict[str, str] = {
    "1.2.840.10008.1.2":       "Implicit VR Little Endian",
    "1.2.840.10008.1.2.1":     "Explicit VR Little Endian",
    "1.2.840.10008.1.2.2":     "Explicit VR Big Endian",
    "1.2.840.10008.1.2.5":     "RLE Lossless",
    "1.2.840.10008.1.2.4.50":  "JPEG Baseline 8-bit",
    "1.2.840.10008.1.2.4.51":  "JPEG Extended 12-bit",
    "1.2.840.10008.1.2.4.57":  "JPEG Lossless Non-Hierarchical",
    "1.2.840.10008.1.2.4.70":  "JPEG Lossless Non-Hierarchical (Process 14 SV1)",
    "1.2.840.10008.1.2.4.80":  "JPEG-LS Lossless",
    "1.2.840.10008.1.2.4.81":  "JPEG-LS Near-Lossless",
    "1.2.840.10008.1.2.4.90":  "JPEG 2000 Lossless",
    "1.2.840.10008.1.2.4.91":  "JPEG 2000",
    "1.2.840.10008.1.2.4.100": "MPEG2 Main Profile",
    "1.2.840.10008.1.2.4.101": "MPEG2 Main Profile High Level",
    "1.2.840.10008.1.2.4.102": "MPEG-4 AVC/H.264 High Profile",
    "1.2.840.10008.1.2.4.103": "MPEG-4 AVC/H.264 BD-Compatible High Profile",
    "1.2.840.10008.1.2.4.104": "MPEG-4 AVC/H.264 High Profile For 2D Video",
    "1.2.840.10008.1.2.4.105": "MPEG-4 AVC/H.264 High Profile For 3D Video",
    "1.2.840.10008.1.2.4.106": "MPEG-4 AVC/H.264 Stereo High Profile",
    "1.2.840.10008.1.2.4.107": "HEVC/H.265 Main Profile",
    "1.2.840.10008.1.2.4.108": "HEVC/H.265 Main 10 Profile",
}

# These transfer syntaxes carry an already-encoded video stream
PASSTHROUGH_SYNTAXES: frozenset[str] = frozenset({
    "1.2.840.10008.1.2.4.100",
    "1.2.840.10008.1.2.4.101",
    "1.2.840.10008.1.2.4.102",
    "1.2.840.10008.1.2.4.103",
    "1.2.840.10008.1.2.4.104",
    "1.2.840.10008.1.2.4.105",
    "1.2.840.10008.1.2.4.106",
    "1.2.840.10008.1.2.4.107",
    "1.2.840.10008.1.2.4.108",
    # MPEG2 variants starting at .200
    "1.2.840.10008.1.2.4.201",
    "1.2.840.10008.1.2.4.202",
    "1.2.840.10008.1.2.4.203",
    "1.2.840.10008.1.2.4.204",
    "1.2.840.10008.1.2.4.205",
})

FRAME_INCREMENT_TEMPORAL: frozenset[str] = frozenset({
    "FrameTime",
    "FrameTimeVector",
    "CineRate",
    "RecommendedDisplayFrameRate",
})


@dataclass
class DicomFileInfo:
    path: Path
    modality: str
    num_frames: int
    transfer_syntax_uid: str
    transfer_syntax_name: str
    is_passthrough: bool
    is_multiframe: bool
    photometric_interpretation: str
    rows: int
    columns: int
    bits_allocated: int
    bits_stored: int
    is_spatial_stack: bool  # True when FrameIncrementPointer points to spatial tags
    warnings: list[str] = field(default_factory=list)


def get_transfer_syntax_name(uid: str) -> str:
    name = TRANSFER_SYNTAX_NAMES.get(uid, "")
    if not name:
        try:
            name = UID(uid).name
        except Exception:
            name = "Unknown"
    return name


def validate_and_load(path: Path) -> DicomFileInfo:
    """
    Validate a file as DICOM and return metadata without loading pixel data.
    Raises DicomValidationError or MissingPixelDataError on failure.
    """
    warnings: list[str] = []
    path = Path(path)

    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True)
    except (InvalidDicomError, Exception) as exc:
        raise DicomValidationError(f"Not a valid DICOM file: {exc}") from exc

    # Transfer syntax — must come from file meta, not dataset
    if ds.file_meta and hasattr(ds.file_meta, "TransferSyntaxUID"):
        ts_uid = str(ds.file_meta.TransferSyntaxUID)
    else:
        ts_uid = "1.2.840.10008.1.2"  # assume Implicit VR LE
        warnings.append("No file meta / TransferSyntaxUID found; assuming Implicit VR Little Endian.")
        logger.info("No TransferSyntaxUID in '%s', assuming Implicit VR Little Endian.", path.name)

    ts_name = get_transfer_syntax_name(ts_uid)

    # With stop_before_pixels=True the PixelData tag is never loaded into ds.
    # Infer presence from image geometry tags — if Rows and Columns are absent
    # this is likely a non-image object (SR, KOS, etc.) with no pixel data.
    if not (hasattr(ds, "Rows") and hasattr(ds, "Columns")):
        raise MissingPixelDataError(
            f"'{path.name}' has no image geometry (Rows/Columns) — "
            "it is likely a non-pixel DICOM object (SR, KOS, etc.)."
        )

    num_frames = _get_int_tag(ds, "NumberOfFrames", default=1)
    is_multiframe = num_frames > 1

    if not is_multiframe:
        warnings.append("File has only 1 frame; will produce a single-frame video.")
        logger.info("'%s' has 1 frame.", path.name)

    modality = getattr(ds, "Modality", "UNKNOWN") or "UNKNOWN"
    photometric = getattr(ds, "PhotometricInterpretation", "UNKNOWN") or "UNKNOWN"
    rows = _get_int_tag(ds, "Rows", default=0)
    cols = _get_int_tag(ds, "Columns", default=0)
    bits_alloc = _get_int_tag(ds, "BitsAllocated", default=8)
    bits_stored = _get_int_tag(ds, "BitsStored", default=8)

    is_spatial = _detect_spatial_stack(ds, warnings)
    is_passthrough = ts_uid in PASSTHROUGH_SYNTAXES

    logger.info(
        "Validated '%s': modality=%s frames=%d ts=%s photometric=%s bits=%d/%d spatial=%s",
        path.name, modality, num_frames, ts_name, photometric, bits_stored, bits_alloc, is_spatial,
    )

    return DicomFileInfo(
        path=path,
        modality=modality,
        num_frames=num_frames,
        transfer_syntax_uid=ts_uid,
        transfer_syntax_name=ts_name,
        is_passthrough=is_passthrough,
        is_multiframe=is_multiframe,
        photometric_interpretation=photometric,
        rows=rows,
        columns=cols,
        bits_allocated=bits_alloc,
        bits_stored=bits_stored,
        is_spatial_stack=is_spatial,
        warnings=warnings,
    )


def open_dataset(path: Path) -> pydicom.Dataset:
    """Open a DICOM file with deferred pixel loading for large files."""
    return pydicom.dcmread(str(path), defer_size="10 MB")


def _get_int_tag(ds: pydicom.Dataset, keyword: str, default: int) -> int:
    val = getattr(ds, keyword, None)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _detect_spatial_stack(ds: pydicom.Dataset, warnings: list[str]) -> bool:
    fip = getattr(ds, "FrameIncrementPointer", None)
    if fip is None:
        return False

    # FrameIncrementPointer can be a single tag or a sequence of tags
    tags = fip if hasattr(fip, "__iter__") and not isinstance(fip, str) else [fip]
    for tag in tags:
        kw = pydicom.datadict.keyword_for_tag(tag) if hasattr(tag, "group") else str(tag)
        if kw in FRAME_INCREMENT_TEMPORAL:
            return False  # it's a cine loop

    warnings.append(
        "FrameIncrementPointer points to spatial tags — this may be a CT/MR volume, "
        "not a cine loop. Converting to video may not be clinically meaningful."
    )
    logger.warning("'%s' appears to be a spatial stack, not a cine loop.", getattr(ds, "filename", "?"))
    return True


def patient_output_path(src: Path, out_root: Path, extension: str) -> Path:
    """
    Build an organised output path:
        out_root / <PatientID> / <StudyDate> / <original_stem>.<ext>

    Falls back to "UNKNOWN_PATIENT" / "UNKNOWN_DATE" when tags are absent.
    Characters unsafe for filesystems are replaced with underscores.
    """
    try:
        ds = pydicom.dcmread(str(src), stop_before_pixels=True)
        patient_id = str(getattr(ds, "PatientID", "") or "").strip()
        study_date = str(getattr(ds, "StudyDate", "") or "").strip()
    except Exception:
        patient_id = ""
        study_date = ""

    def _sanitize(s: str, fallback: str) -> str:
        s = s.strip()
        if not s:
            return fallback
        return re.sub(r'[^\w\-]', '_', s)

    pid_dir = _sanitize(patient_id, "UNKNOWN_PATIENT")
    date_dir = _sanitize(study_date, "UNKNOWN_DATE")
    ext = extension.lstrip(".")
    return out_root / pid_dir / date_dir / f"{src.stem}.{ext}"
