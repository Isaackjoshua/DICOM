"""
Lazy frame iterator using pydicom 3's iter_pixels API.

iter_pixels handles all transfer syntaxes (JPEG, JPEG-LS, JPEG 2000, RLE,
uncompressed, Big Endian) and converts YBR_FULL / YBR_FULL_422 → RGB automatically.
Passing the file path (rather than a pre-loaded Dataset) keeps memory flat for
large cine loops — only one decoded frame lives in memory at a time.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Optional

import numpy as np
import pydicom
from pydicom.pixels import iter_pixels

from src.core.pixel_pipeline import VolumeScalars, build_volume_scalars, process_frame
from src.utils.exceptions import MissingPixelDataError, UnsupportedTransferSyntaxError

logger = logging.getLogger(__name__)

# Transfer syntaxes whose PixelData is an already-encoded video stream
PASSTHROUGH_SYNTAXES = frozenset({
    "1.2.840.10008.1.2.4.100",
    "1.2.840.10008.1.2.4.101",
    "1.2.840.10008.1.2.4.102",
    "1.2.840.10008.1.2.4.103",
    "1.2.840.10008.1.2.4.104",
    "1.2.840.10008.1.2.4.105",
    "1.2.840.10008.1.2.4.106",
    "1.2.840.10008.1.2.4.107",
    "1.2.840.10008.1.2.4.108",
    "1.2.840.10008.1.2.4.201",
    "1.2.840.10008.1.2.4.202",
    "1.2.840.10008.1.2.4.203",
    "1.2.840.10008.1.2.4.204",
    "1.2.840.10008.1.2.4.205",
})

# After iter_pixels(raw=False), YBR frames are converted to RGB
_YBR_OUTPUTS_AS_RGB = frozenset({
    "YBR_FULL",
    "YBR_FULL_422",
    "YBR_PARTIAL_422",
    "YBR_PARTIAL_420",
})


def iter_frames(
    ds: pydicom.Dataset,
    ts_uid: str,
    raw_mode: bool = False,
    cancel_event=None,
) -> Iterator[np.ndarray]:
    """
    Yield fully-processed uint8 frames one at a time.

    Parameters
    ----------
    ds          : loaded Dataset (from open_dataset — deferred pixel data is fine)
    ts_uid      : transfer syntax UID (read from file_meta before calling)
    raw_mode    : skip VOI LUT and 8-bit mapping — return nearly-raw data
    cancel_event: threading.Event; iteration stops when set
    """
    if ts_uid in PASSTHROUGH_SYNTAXES:
        raise UnsupportedTransferSyntaxError(
            ts_uid,
            "Passthrough syntax — call conversion_service for stream-copy path.",
        )

    if not hasattr(ds, "PixelData"):
        raise MissingPixelDataError("Dataset has no PixelData.")

    photometric = (getattr(ds, "PhotometricInterpretation", "") or "").strip()
    num_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    bits_alloc = int(getattr(ds, "BitsAllocated", 8) or 8)
    rows = int(ds.Rows)
    cols = int(ds.Columns)

    logger.info(
        "iter_frames: %d frame(s), %dx%d, %d-bit, pi=%s, ts=%s",
        num_frames, cols, rows, bits_alloc, photometric, ts_uid,
    )

    # iter_pixels converts YBR → RGB, so tell the pipeline the frames are RGB
    effective_photometric = "RGB" if photometric in _YBR_OUTPUTS_AS_RGB else photometric

    scalars: Optional[VolumeScalars] = None

    src = Path(ds.filename) if hasattr(ds, "filename") and ds.filename else ds

    try:
        frame_gen = iter_pixels(src, raw=False)
    except Exception as exc:
        raise UnsupportedTransferSyntaxError(ts_uid, str(exc)) from exc

    for idx, raw_frame in enumerate(frame_gen):
        if cancel_event and cancel_event.is_set():
            logger.info("Frame extraction cancelled at frame %d.", idx)
            return

        if scalars is None:
            scalars = build_volume_scalars(raw_frame, ds)
            logger.info(
                "Volume scalars locked: p_low=%.1f p_high=%.1f windowing=%s",
                scalars.p_low, scalars.p_high, scalars.used_windowing,
            )

        yield process_frame(
            raw_frame,
            ds,
            scalars,
            raw_mode=raw_mode,
            photometric_override=effective_photometric,
        )

        if idx + 1 >= num_frames:
            break  # guard against iter_pixels yielding extra frames
