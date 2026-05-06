"""
FFmpeg stdin pipe writer.
Never uses cv2.VideoWriter — quality is too poor for medical use.
"""

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from src.utils.exceptions import FFmpegEncodingError
from src.utils.ffmpeg_utils import (
    build_rawvideo_command,
    build_streamcopy_command,
    get_codec_args,
)

logger = logging.getLogger(__name__)

_STDERR_TAIL_LINES = 40


class VideoWriter:
    """
    Context-manager that pipes raw uint8 frames to FFmpeg.

    Usage::

        with VideoWriter(ffmpeg, "output.mp4", w, h, fps, "high", is_gray=True) as w:
            for frame in frames:
                w.write_frame(frame)
    """

    def __init__(
        self,
        ffmpeg_path: str,
        output_path: str | Path,
        width: int,
        height: int,
        fps: float,
        preset: str = "high",
        is_grayscale: bool = True,
        cancel_event: Optional[threading.Event] = None,
    ):
        self._ffmpeg = ffmpeg_path
        self._output = Path(output_path)
        self._width = width
        self._height = height
        self._fps = fps
        self._preset = preset
        self._is_grayscale = is_grayscale
        self._cancel = cancel_event
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_lines: list[str] = []
        self._stderr_thread: Optional[threading.Thread] = None
        self._frames_written = 0

    def __enter__(self) -> "VideoWriter":
        self._output.parent.mkdir(parents=True, exist_ok=True)
        ext = self._output.suffix.lower().lstrip(".")
        pix_fmt = "gray" if self._is_grayscale else "rgb24"
        codec_args = get_codec_args(self._preset, ext, self._is_grayscale)

        cmd = build_rawvideo_command(
            ffmpeg_path=self._ffmpeg,
            pix_fmt=pix_fmt,
            width=self._width,
            height=self._height,
            fps=self._fps,
            codec_args=codec_args,
            output_path=str(self._output),
        )
        logger.info("Starting FFmpeg: %s", " ".join(cmd))

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._stderr_thread = threading.Thread(
            target=self._collect_stderr, daemon=True
        )
        self._stderr_thread.start()
        return self

    def write_frame(self, frame: np.ndarray) -> None:
        if self._cancel and self._cancel.is_set():
            return
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("VideoWriter is not open.")
        self._proc.stdin.write(frame.tobytes())
        self._frames_written += 1

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        cancelled = self._cancel and self._cancel.is_set()
        output_existed = False

        if self._proc:
            if self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except BrokenPipeError:
                    pass
            returncode = self._proc.wait(timeout=60)

            if self._stderr_thread:
                self._stderr_thread.join(timeout=5)

            if cancelled:
                # Remove partial output
                if self._output.exists():
                    try:
                        self._output.unlink()
                        logger.info("Cancelled — removed partial output '%s'.", self._output)
                    except OSError as e:
                        logger.warning("Could not remove partial output: %s", e)
            elif exc_type is None and returncode != 0:
                stderr_tail = "\n".join(self._stderr_lines[-_STDERR_TAIL_LINES:])
                # Clean up the broken output file
                if self._output.exists():
                    try:
                        self._output.unlink()
                    except OSError:
                        pass
                raise FFmpegEncodingError(returncode, stderr_tail)

        return False  # don't suppress exceptions

    def _collect_stderr(self) -> None:
        if self._proc and self._proc.stderr:
            for line in self._proc.stderr:
                decoded = line.decode("utf-8", errors="replace").rstrip()
                self._stderr_lines.append(decoded)

    @property
    def frames_written(self) -> int:
        return self._frames_written


class StreamCopyWriter:
    """Write an encapsulated MPEG/H.264/HEVC stream via stream-copy (zero re-encode)."""

    def __init__(
        self,
        ffmpeg_path: str,
        output_path: str | Path,
        cancel_event: Optional[threading.Event] = None,
    ):
        self._ffmpeg = ffmpeg_path
        self._output = Path(output_path)
        self._cancel = cancel_event
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_lines: list[str] = []

    def write_stream(self, data: bytes) -> None:
        """Write a complete elementary stream in one call."""
        self._output.parent.mkdir(parents=True, exist_ok=True)
        cmd = build_streamcopy_command(self._ffmpeg, str(self._output))
        logger.info("Stream-copy FFmpeg: %s", " ".join(cmd))

        proc = subprocess.run(
            cmd,
            input=data,
            capture_output=True,
            timeout=300,
        )
        if proc.returncode != 0 and not (self._cancel and self._cancel.is_set()):
            stderr = proc.stderr.decode("utf-8", errors="replace")
            tail = "\n".join(stderr.splitlines()[-_STDERR_TAIL_LINES:])
            if self._output.exists():
                try:
                    self._output.unlink()
                except OSError:
                    pass
            raise FFmpegEncodingError(proc.returncode, tail)

        if self._cancel and self._cancel.is_set() and self._output.exists():
            try:
                self._output.unlink()
            except OSError:
                pass
