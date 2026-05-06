"""FFmpeg binary discovery, version probing, and command building."""

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.utils.exceptions import FFmpegNotFoundError

logger = logging.getLogger(__name__)

_INSTALL_INSTRUCTIONS = """
FFmpeg is required but was not found on your system.

Install instructions:
  Windows : winget install Gyan.FFmpeg
            OR download from https://www.gyan.dev/ffmpeg/builds/ and add to PATH
  macOS   : brew install ffmpeg
  Linux   : sudo apt install ffmpeg   (Debian/Ubuntu)
            sudo dnf install ffmpeg   (Fedora)
            sudo pacman -S ffmpeg     (Arch)

After installing, restart this application.
""".strip()


@dataclass(frozen=True)
class FFmpegInfo:
    path: str
    version: str
    raw_output: str


def locate_ffmpeg() -> str:
    """Return the path to the ffmpeg binary, or raise FFmpegNotFoundError."""
    candidate = shutil.which("ffmpeg")
    if candidate:
        return candidate

    # Common non-PATH locations
    extra_paths = [
        Path("/usr/local/bin/ffmpeg"),
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
    ]
    for p in extra_paths:
        if p.exists():
            return str(p)

    raise FFmpegNotFoundError(
        "FFmpeg binary not found.\n\n" + _INSTALL_INSTRUCTIONS
    )


def probe_ffmpeg(ffmpeg_path: str | None = None) -> FFmpegInfo:
    """Run ``ffmpeg -version`` and return parsed info."""
    path = ffmpeg_path or locate_ffmpeg()
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise FFmpegNotFoundError(f"Cannot execute FFmpeg at '{path}': {exc}") from exc

    raw = result.stdout + result.stderr
    match = re.search(r"ffmpeg version (\S+)", raw)
    version = match.group(1) if match else "unknown"
    logger.info("FFmpeg found at '%s', version %s", path, version)
    return FFmpegInfo(path=path, version=version, raw_output=raw)


def get_install_instructions() -> str:
    return _INSTALL_INSTRUCTIONS


def build_rawvideo_command(
    ffmpeg_path: str,
    pix_fmt: str,
    width: int,
    height: int,
    fps: float,
    codec_args: list[str],
    output_path: str,
) -> list[str]:
    """Build an FFmpeg command that reads rawvideo from stdin."""
    return [
        ffmpeg_path,
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", pix_fmt,
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
        *codec_args,
        "-movflags", "+faststart",
        output_path,
    ]


def build_streamcopy_command(
    ffmpeg_path: str,
    output_path: str,
) -> list[str]:
    """Build an FFmpeg command that copies an elementary stream from stdin."""
    return [
        ffmpeg_path,
        "-y",
        "-i", "pipe:0",
        "-c", "copy",
        output_path,
    ]


CODEC_PRESETS: dict[str, dict[str, list[str]]] = {
    "lossless": {
        "mp4": ["-c:v", "libx264", "-preset", "veryslow", "-crf", "0", "-pix_fmt", "yuv444p", "-color_range", "pc"],
        "avi": ["-c:v", "ffv1", "-level", "3"],
        "mkv": ["-c:v", "ffv1", "-level", "3"],
    },
    "high": {
        "mp4": ["-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p", "-color_range", "pc"],
        "avi": ["-c:v", "ffv1", "-level", "3"],
        "mkv": ["-c:v", "ffv1", "-level", "3"],
    },
    "compressed": {
        "mp4": ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"],
        "avi": ["-c:v", "mpeg4", "-q:v", "3"],
        "mkv": ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"],
    },
}


def get_codec_args(preset: str, container: str, is_grayscale: bool) -> list[str]:
    """Return the codec argument list for a given preset/container/color combination."""
    preset = preset.lower()
    container = container.lower().lstrip(".")
    if container not in ("mp4", "avi", "mkv"):
        container = "mp4"
    if preset not in CODEC_PRESETS:
        logger.warning("Unknown preset '%s', falling back to 'high'.", preset)
        preset = "high"

    args = list(CODEC_PRESETS[preset][container])

    # For grayscale lossless/high, avoid yuv420p chroma subsampling
    if is_grayscale and preset in ("lossless", "high") and container in ("mp4", "mkv"):
        for i, arg in enumerate(args):
            if arg == "yuv420p":
                args[i] = "gray"
                break
    return args
