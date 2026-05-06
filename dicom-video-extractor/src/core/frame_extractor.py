"""
Lazy frame iterator that yields one processed uint8 numpy frame at a time.
Never materialises the full (N, H, W[, 3]) array for large files.
"""

import logging
from collections.abc import Iterator
from typing import Optional

import numpy as np
import pydicom
from pydicom.encaps import generate_pixel_data_frame

from src.core.pixel_pipeline import VolumeScalars, build_volume_scalars, process_frame
from src.utils.exceptions import MissingPixelDataError, UnsupportedTransferSyntaxError

logger = logging.getLogger(__name__)

# Transfer syntaxes that are plain uncompressed pixel data
UNCOMPRESSED_SYNTAXES = frozenset({
    "1.2.840.10008.1.2",    # Implicit VR LE
    "1.2.840.10008.1.2.1",  # Explicit VR LE
    "1.2.840.10008.1.2.2",  # Explicit VR BE
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
    ds          : loaded pydicom Dataset (pixel data present)
    ts_uid      : transfer syntax UID string (read from file_meta before calling)
    raw_mode    : skip windowing / scaling — pass frames through mostly raw
    cancel_event: threading.Event; iteration stops cleanly when set
    """
    if not hasattr(ds, "PixelData"):
        raise MissingPixelDataError("Dataset has no PixelData.")

    num_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    rows = int(ds.Rows)
    cols = int(ds.Columns)
    bits_alloc = int(getattr(ds, "BitsAllocated", 8))
    samples_per_pixel = int(getattr(ds, "SamplesPerPixel", 1))
    is_encapsulated = ts_uid not in UNCOMPRESSED_SYNTAXES

    logger.info(
        "Extracting %d frame(s), %dx%d, %d-bit, %d spp, encapsulated=%s",
        num_frames, cols, rows, bits_alloc, samples_per_pixel, is_encapsulated,
    )

    scalars: Optional[VolumeScalars] = None

    if is_encapsulated:
        yield from _iter_encapsulated(
            ds, ts_uid, num_frames, raw_mode, cancel_event,
            rows, cols, scalars
        )
    else:
        yield from _iter_uncompressed(
            ds, num_frames, bits_alloc, samples_per_pixel,
            rows, cols, raw_mode, cancel_event
        )


def _iter_uncompressed(
    ds: pydicom.Dataset,
    num_frames: int,
    bits_alloc: int,
    samples_per_pixel: int,
    rows: int,
    cols: int,
    raw_mode: bool,
    cancel_event,
) -> Iterator[np.ndarray]:
    pixel_bytes: bytes = ds.PixelData
    dtype = np.uint16 if bits_alloc == 16 else np.uint8
    frame_pixels = rows * cols * samples_per_pixel
    frame_bytes = frame_pixels * (bits_alloc // 8)

    scalars: Optional[VolumeScalars] = None

    for i in range(num_frames):
        if cancel_event and cancel_event.is_set():
            logger.info("Frame extraction cancelled at frame %d.", i)
            return

        start = i * frame_bytes
        raw = pixel_bytes[start: start + frame_bytes]
        frame = np.frombuffer(raw, dtype=dtype).reshape(
            (rows, cols, samples_per_pixel) if samples_per_pixel > 1 else (rows, cols)
        ).copy()

        if scalars is None:
            scalars = build_volume_scalars(frame, ds)

        yield process_frame(frame, ds, scalars, raw_mode=raw_mode)


def _iter_encapsulated(
    ds: pydicom.Dataset,
    ts_uid: str,
    num_frames: int,
    raw_mode: bool,
    cancel_event,
    rows: int,
    cols: int,
    scalars: Optional[VolumeScalars],
) -> Iterator[np.ndarray]:
    try:
        pixel_data = ds.PixelData
        frame_gen = generate_pixel_data_frame(pixel_data, num_frames)
    except Exception as exc:
        raise UnsupportedTransferSyntaxError(ts_uid, str(exc)) from exc

    for i, frame_bytes in enumerate(frame_gen):
        if cancel_event and cancel_event.is_set():
            logger.info("Frame extraction cancelled at frame %d.", i)
            return

        try:
            # Let pydicom's configured handlers decode this fragment
            frame_ds = _make_single_frame_ds(ds, frame_bytes)
            frame = frame_ds.pixel_array
        except Exception as exc:
            raise UnsupportedTransferSyntaxError(
                ts_uid, f"Failed to decode frame {i}: {exc}"
            ) from exc

        if scalars is None:
            scalars = build_volume_scalars(frame, ds)

        yield process_frame(frame, ds, scalars, raw_mode=raw_mode)


def _make_single_frame_ds(ds: pydicom.Dataset, frame_bytes: bytes) -> pydicom.Dataset:
    """Create a minimal single-frame Dataset for decoding one fragment."""
    import copy
    from pydicom.encaps import encapsulate

    mini = copy.copy(ds)
    mini.NumberOfFrames = 1
    mini.PixelData = encapsulate([frame_bytes])
    mini["PixelData"].is_undefined_length = True
    return mini
