"""Orchestrates: read → extract → process → write for a single DICOM file."""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pydicom
from pydicom.encaps import generate_frames as generate_pixel_data_frame

from src.core.dicom_reader import (
    PASSTHROUGH_SYNTAXES,
    DicomFileInfo,
    open_dataset,
    validate_and_load,
)
from src.core.fps_resolver import FpsResult, resolve_fps
from src.core.frame_extractor import iter_frames
from src.core.video_writer import StreamCopyWriter, VideoWriter
from src.utils.exceptions import (
    DicomValidationError,
    FFmpegEncodingError,
    MissingPixelDataError,
    UnsupportedTransferSyntaxError,
)

logger = logging.getLogger(__name__)


@dataclass
class ConversionRequest:
    input_path: Path
    output_path: Path
    preset: str = "high"              # lossless | high | compressed
    fps_override: Optional[float] = None
    raw_mode: bool = False
    force_reencode: bool = False      # ignore passthrough even for MPEG encapsulated
    include_single_frame: bool = True


@dataclass
class ConversionResult:
    input_path: Path
    output_path: Path
    success: bool
    frames_written: int = 0
    fps_result: Optional[FpsResult] = None
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None


ProgressCallback = Callable[[int, int], None]  # (current_frame, total_frames)
LogCallback = Callable[[str, str], None]        # (message, level)


def convert(
    request: ConversionRequest,
    ffmpeg_path: str,
    progress_cb: Optional[ProgressCallback] = None,
    log_cb: Optional[LogCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> ConversionResult:
    """
    Full conversion pipeline for one DICOM file.
    Designed to be called from a worker thread.
    """
    def _log(msg: str, level: str = "INFO") -> None:
        getattr(logger, level.lower(), logger.info)(msg)
        if log_cb:
            log_cb(msg, level)

    result = ConversionResult(
        input_path=request.input_path,
        output_path=request.output_path,
        success=False,
    )

    try:
        # Validate
        _log(f"Validating '{request.input_path.name}'…")
        info: DicomFileInfo = validate_and_load(request.input_path)
        for w in info.warnings:
            _log(w, "WARNING")
            result.warnings.append(w)

        if info.is_spatial_stack:
            msg = (
                f"'{request.input_path.name}' appears to be a spatial stack, not cine. "
                "Proceeding with conversion as instructed."
            )
            _log(msg, "WARNING")
            result.warnings.append(msg)

        # Open dataset with deferred pixels
        ds: pydicom.Dataset = open_dataset(request.input_path)

        # FPS
        fps_result = resolve_fps(ds, user_override=request.fps_override)
        result.fps_result = fps_result
        if fps_result.warning:
            _log(fps_result.warning, "WARNING")
            result.warnings.append(fps_result.warning)
        _log(f"FPS: {fps_result.fps:.4f} (source: {fps_result.source})")

        # Passthrough path
        if info.is_passthrough and not request.force_reencode:
            _log("Transfer syntax is MPEG-encapsulated — using stream-copy (zero re-encode).")
            return _passthrough_convert(ds, info, request, ffmpeg_path, result, _log, cancel_event)

        # Frame-by-frame encoding path
        return _frame_encode(
            ds, info, request, fps_result, ffmpeg_path,
            result, _log, progress_cb, cancel_event
        )

    except (DicomValidationError, MissingPixelDataError, UnsupportedTransferSyntaxError) as exc:
        result.error = str(exc)
        _log(str(exc), "ERROR")
        return result
    except FFmpegEncodingError as exc:
        result.error = str(exc)
        _log(str(exc), "ERROR")
        if exc.stderr_tail:
            _log(f"FFmpeg stderr:\n{exc.stderr_tail}", "ERROR")
        return result
    except Exception as exc:
        result.error = f"Unexpected error: {exc}"
        _log(result.error, "ERROR")
        logger.exception("Unexpected error during conversion of '%s'", request.input_path)
        return result


def _passthrough_convert(
    ds: pydicom.Dataset,
    info: DicomFileInfo,
    request: ConversionRequest,
    ffmpeg_path: str,
    result: ConversionResult,
    _log,
    cancel_event,
) -> ConversionResult:
    _log("Concatenating encapsulated stream fragments…")
    fragments: list[bytes] = []
    for fragment in generate_pixel_data_frame(ds.PixelData, number_of_frames=info.num_frames):
        fragments.append(fragment)
    stream_data = b"".join(fragments)
    _log(f"Stream size: {len(stream_data) / 1024 / 1024:.1f} MB")

    writer = StreamCopyWriter(ffmpeg_path, request.output_path, cancel_event)
    writer.write_stream(stream_data)

    if cancel_event and cancel_event.is_set():
        _log("Conversion cancelled.", "WARNING")
        return result

    result.success = True
    result.frames_written = info.num_frames
    _log(f"Stream-copy complete → '{request.output_path}'")
    return result


def _frame_encode(
    ds: pydicom.Dataset,
    info: DicomFileInfo,
    request: ConversionRequest,
    fps_result: FpsResult,
    ffmpeg_path: str,
    result: ConversionResult,
    _log,
    progress_cb,
    cancel_event,
) -> ConversionResult:
    photometric = info.photometric_interpretation
    is_grayscale = "MONO" in photometric or "GRAY" in photometric or photometric == ""
    total = info.num_frames

    _log(
        f"Encoding {total} frame(s), {info.columns}x{info.rows}, "
        f"{fps_result.fps:.2f} fps, preset={request.preset}"
    )

    frame_iter = iter_frames(
        ds,
        ts_uid=info.transfer_syntax_uid,
        raw_mode=request.raw_mode,
        cancel_event=cancel_event,
    )

    with VideoWriter(
        ffmpeg_path=ffmpeg_path,
        output_path=request.output_path,
        width=info.columns,
        height=info.rows,
        fps=fps_result.fps,
        preset=request.preset,
        is_grayscale=is_grayscale,
        cancel_event=cancel_event,
    ) as vw:
        for idx, frame in enumerate(frame_iter):
            if cancel_event and cancel_event.is_set():
                _log("Conversion cancelled.", "WARNING")
                return result
            vw.write_frame(frame)
            if progress_cb:
                progress_cb(idx + 1, total)

        result.frames_written = vw.frames_written

    if cancel_event and cancel_event.is_set():
        return result

    result.success = True
    _log(
        f"Done — wrote {result.frames_written}/{total} frames → '{request.output_path}'"
    )
    return result
