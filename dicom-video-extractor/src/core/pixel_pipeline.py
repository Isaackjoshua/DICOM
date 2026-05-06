"""
Per-frame pixel processing pipeline (apply in this order):
  1. Modality LUT (RescaleSlope / RescaleIntercept)
  2. VOI LUT / windowing (>8-bit only, unless raw mode)
  3. MONOCHROME1 inversion
  4. Color space conversion (YBR variants, PALETTE COLOR) → RGB
     (skip when iter_pixels already converted — pass photometric_override='RGB')
  5. 16/32→8 bit scaling using per-volume percentile scalars
  6. Pixel aspect ratio correction (PixelSpacing rows ≠ cols)
  7. Return uint8 C-contiguous (H,W) grayscale or (H,W,3) RGB
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
import pydicom

try:
    from pydicom.pixels import apply_voi_lut, convert_color_space, apply_color_lut
except ImportError:
    from pydicom.pixel_data_handlers.util import apply_voi_lut, convert_color_space
    from pydicom.pixel_data_handlers.util import apply_color_lut  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class VolumeScalars:
    """Computed once on the first frame; reused for all frames to avoid flicker."""
    p_low: float = 0.0
    p_high: float = 255.0
    computed: bool = False
    used_windowing: bool = False


def build_volume_scalars(
    first_frame_raw: np.ndarray,
    ds: pydicom.Dataset,
) -> VolumeScalars:
    """
    Determine per-volume normalisation scalars from the first decoded frame.
    Uses WindowCenter/WindowWidth if available; otherwise 1st/99th percentile.
    """
    wc = getattr(ds, "WindowCenter", None)
    ww = getattr(ds, "WindowWidth", None)
    if wc is not None and ww is not None:
        try:
            wc_val = float(wc[0] if hasattr(wc, "__iter__") else wc)
            ww_val = float(ww[0] if hasattr(ww, "__iter__") else ww)
            low = wc_val - ww_val / 2.0
            high = wc_val + ww_val / 2.0
            logger.info("Volume scalars from WindowCenter/Width: [%.1f, %.1f]", low, high)
            return VolumeScalars(p_low=low, p_high=high, computed=True, used_windowing=True)
        except (TypeError, ValueError, IndexError):
            pass

    flat = first_frame_raw.astype(np.float64).ravel()
    if len(flat) == 0:
        return VolumeScalars(p_low=0.0, p_high=255.0, computed=True)

    p1, p99 = float(np.percentile(flat, 1)), float(np.percentile(flat, 99))
    if p1 >= p99:
        p1, p99 = float(flat.min()), float(flat.max())
    if p1 >= p99:
        p1, p99 = 0.0, 255.0
    logger.info("Volume scalars from 1st/99th percentile: [%.1f, %.1f]", p1, p99)
    return VolumeScalars(p_low=p1, p_high=p99, computed=True, used_windowing=False)


def process_frame(
    frame: np.ndarray,
    ds: pydicom.Dataset,
    scalars: VolumeScalars,
    raw_mode: bool = False,
    photometric_override: Optional[str] = None,
) -> np.ndarray:
    """
    Full pixel pipeline for one decoded frame.
    `photometric_override` should be set to 'RGB' when iter_pixels already
    converted YBR→RGB so we skip the redundant color conversion step.
    """
    photometric = (
        photometric_override
        if photometric_override is not None
        else (getattr(ds, "PhotometricInterpretation", "") or "").strip()
    )
    bits_stored = int(getattr(ds, "BitsStored", 8) or 8)

    # Step 1 — Modality LUT
    frame = _apply_modality_lut(frame, ds)

    # Step 2 — VOI LUT / windowing (only for >8-bit and not raw mode)
    if not raw_mode and bits_stored > 8:
        if scalars.used_windowing:
            try:
                frame = apply_voi_lut(frame, ds)
            except Exception as exc:
                logger.warning("apply_voi_lut failed (%s); using manual window.", exc)
                frame = _manual_window(frame, scalars)
        else:
            frame = _manual_window(frame, scalars)

    # Step 3 — MONOCHROME1 inversion
    if photometric == "MONOCHROME1":
        frame = _invert(frame)
        logger.debug("MONOCHROME1 inversion applied.")

    # Step 4 — Color space conversion → RGB
    # Skip if iter_pixels already handled YBR→RGB (photometric_override='RGB')
    if photometric_override is None:
        frame = _convert_to_rgb(frame, ds, photometric)

    # Step 5 — Scale to uint8 (handles 8/12/16/32-bit input)
    frame = _to_uint8(frame, scalars, bits_stored, raw_mode)

    # Step 6 — Pixel aspect ratio correction
    frame = _apply_pixel_spacing(frame, ds)

    # Ensure C-contiguous
    if not frame.flags["C_CONTIGUOUS"]:
        frame = np.ascontiguousarray(frame)

    return frame


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_modality_lut(frame: np.ndarray, ds: pydicom.Dataset) -> np.ndarray:
    slope = getattr(ds, "RescaleSlope", None)
    intercept = getattr(ds, "RescaleIntercept", None)
    if slope is None and intercept is None:
        return frame
    slope = float(slope) if slope is not None else 1.0
    intercept = float(intercept) if intercept is not None else 0.0
    if slope == 1.0 and intercept == 0.0:
        return frame
    result = frame.astype(np.float64) * slope + intercept
    logger.debug("Modality LUT: slope=%.4f intercept=%.4f", slope, intercept)
    return result


def _manual_window(frame: np.ndarray, scalars: VolumeScalars) -> np.ndarray:
    low, high = scalars.p_low, scalars.p_high
    if high <= low:
        return frame
    clipped = np.clip(frame.astype(np.float64), low, high)
    return (clipped - low) / (high - low) * 255.0


def _invert(frame: np.ndarray) -> np.ndarray:
    max_val = frame.max()
    return max_val - frame


def _convert_to_rgb(
    frame: np.ndarray, ds: pydicom.Dataset, photometric: str
) -> np.ndarray:
    planar_config = int(getattr(ds, "PlanarConfiguration", 0) or 0)

    if photometric in ("RGB", "MONOCHROME1", "MONOCHROME2", ""):
        return frame

    if photometric in ("YBR_FULL", "YBR_FULL_422", "YBR_PARTIAL_422", "YBR_PARTIAL_420"):
        if planar_config == 1 and frame.ndim == 3:
            frame = np.ascontiguousarray(frame.transpose(1, 2, 0))
        try:
            frame = convert_color_space(frame, photometric, "RGB")
        except Exception as exc:
            logger.warning("pydicom color convert failed (%s); trying OpenCV.", exc)
            frame = cv2.cvtColor(frame.astype(np.uint8), cv2.COLOR_YCrCb2RGB)
        return frame

    if photometric == "PALETTE COLOR":
        try:
            frame = apply_color_lut(frame, ds)
        except Exception as exc:
            logger.warning("Palette color conversion failed: %s", exc)
        return frame

    logger.warning("Unknown PhotometricInterpretation '%s'; passing frame through.", photometric)
    return frame


def _to_uint8(
    frame: np.ndarray,
    scalars: VolumeScalars,
    bits_stored: int,
    raw_mode: bool,
) -> np.ndarray:
    if frame.dtype == np.uint8:
        return frame

    arr = frame.astype(np.float64)

    if raw_mode or bits_stored <= 8:
        np.clip(arr, 0, 255, out=arr)
        return arr.astype(np.uint8)

    # Map through the pre-computed volume scalars
    low, high = scalars.p_low, scalars.p_high
    if high <= low:
        high = low + 1.0
    np.clip(arr, low, high, out=arr)
    arr = (arr - low) / (high - low) * 255.0
    return arr.astype(np.uint8)


def _apply_pixel_spacing(frame: np.ndarray, ds: pydicom.Dataset) -> np.ndarray:
    """
    Correct non-square pixels by resizing.
    PixelSpacing = [row_spacing, col_spacing] in mm.
    If row_spacing ≠ col_spacing, the image is geometrically distorted.
    We resize to square pixels by scaling the dimension with smaller spacing
    (higher spatial resolution) to match the other axis.
    """
    ps = getattr(ds, "PixelSpacing", None)
    if ps is None or len(ps) < 2:
        return frame

    try:
        row_sp = float(ps[0])
        col_sp = float(ps[1])
    except (TypeError, ValueError, IndexError):
        return frame

    if row_sp <= 0 or col_sp <= 0 or abs(row_sp - col_sp) / max(row_sp, col_sp) < 0.001:
        return frame  # square pixels — nothing to do

    h, w = frame.shape[:2]
    # Scale height to correct for row spacing relative to column spacing
    new_h = int(round(h * row_sp / col_sp))

    if new_h == h:
        return frame

    logger.info(
        "Pixel spacing correction: PixelSpacing=[%.3f, %.3f], "
        "resizing %dx%d → %dx%d",
        row_sp, col_sp, w, h, w, new_h,
    )
    return cv2.resize(frame, (w, new_h), interpolation=cv2.INTER_LINEAR)
