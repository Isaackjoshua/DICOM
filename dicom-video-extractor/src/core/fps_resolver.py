"""FPS detection chain with documented fallbacks."""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pydicom

logger = logging.getLogger(__name__)

DEFAULT_FPS = 30.0
NON_UNIFORM_THRESHOLD = 0.05  # 5% coefficient of variation triggers a warning


@dataclass
class FpsResult:
    fps: float
    source: str          # which tag/method provided the value
    warning: str = ""    # non-empty when user should be informed


def resolve_fps(ds: pydicom.Dataset, user_override: Optional[float] = None) -> FpsResult:
    """
    Determine frame rate using the priority chain defined in the spec.
    Returns an FpsResult whose .source explains the origin of the value.
    """
    if user_override is not None and user_override > 0:
        logger.info("Using user-supplied FPS override: %.4f fps.", user_override)
        return FpsResult(fps=float(user_override), source="user_override")

    # 1. CineRate (0018,0040)
    result = _try_cine_rate(ds)
    if result:
        return result

    # 2. RecommendedDisplayFrameRate (0008,2144)
    result = _try_recommended_display_frame_rate(ds)
    if result:
        return result

    # 3. FrameTime (0018,1063)
    result = _try_frame_time(ds)
    if result:
        return result

    # 4. FrameTimeVector (0018,1065)
    result = _try_frame_time_vector(ds)
    if result:
        return result

    # 5. Default fallback
    logger.warning(
        "No FPS metadata found in dataset; falling back to default %.1f fps. "
        "Check CineRate / FrameTime tags.",
        DEFAULT_FPS,
    )
    return FpsResult(
        fps=DEFAULT_FPS,
        source="default_fallback",
        warning=f"No FPS metadata found. Using default {DEFAULT_FPS} fps.",
    )


def _try_cine_rate(ds: pydicom.Dataset) -> Optional[FpsResult]:
    val = getattr(ds, "CineRate", None)
    if val is None:
        return None
    try:
        fps = float(val)
        if fps > 0:
            logger.info("FPS resolved from CineRate: %.4f fps.", fps)
            return FpsResult(fps=fps, source="CineRate")
    except (ValueError, TypeError):
        pass
    return None


def _try_recommended_display_frame_rate(ds: pydicom.Dataset) -> Optional[FpsResult]:
    val = getattr(ds, "RecommendedDisplayFrameRate", None)
    if val is None:
        return None
    try:
        fps = float(val)
        if fps > 0:
            logger.info("FPS resolved from RecommendedDisplayFrameRate: %.4f fps.", fps)
            return FpsResult(fps=fps, source="RecommendedDisplayFrameRate")
    except (ValueError, TypeError):
        pass
    return None


def _try_frame_time(ds: pydicom.Dataset) -> Optional[FpsResult]:
    val = getattr(ds, "FrameTime", None)
    if val is None:
        return None
    try:
        ms = float(val)
        if ms > 0:
            fps = 1000.0 / ms
            logger.info("FPS resolved from FrameTime (%s ms): %.4f fps.", ms, fps)
            return FpsResult(fps=fps, source="FrameTime")
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return None


def _try_frame_time_vector(ds: pydicom.Dataset) -> Optional[FpsResult]:
    val = getattr(ds, "FrameTimeVector", None)
    if val is None:
        return None
    try:
        vec = np.array([float(v) for v in val], dtype=np.float64)
        vec = vec[vec > 0]
        if len(vec) == 0:
            return None

        mean_ms = float(np.mean(vec))
        fps = 1000.0 / mean_ms

        warning = ""
        if len(vec) > 1:
            cv = float(np.std(vec) / mean_ms)
            if cv > NON_UNIFORM_THRESHOLD:
                warning = (
                    f"FrameTimeVector is non-uniform (CV={cv:.1%}). "
                    f"Using mean frame time {mean_ms:.2f} ms → {fps:.4f} fps."
                )
                logger.warning(warning)

        logger.info("FPS resolved from FrameTimeVector (mean %.2f ms): %.4f fps.", mean_ms, fps)
        return FpsResult(fps=fps, source="FrameTimeVector", warning=warning)
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return None
