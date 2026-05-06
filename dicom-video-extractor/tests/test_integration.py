"""
End-to-end integration tests.
These require FFmpeg and are skipped if it's not installed.
"""

import subprocess
import json
from pathlib import Path

import pydicom.data
import pytest

from src.core.dicom_reader import validate_and_load
from src.services.conversion_service import ConversionRequest, convert
from src.utils.exceptions import FFmpegNotFoundError
from src.utils.ffmpeg_utils import locate_ffmpeg


@pytest.fixture(scope="session")
def ffmpeg_path():
    try:
        return locate_ffmpeg()
    except FFmpegNotFoundError:
        pytest.skip("FFmpeg not installed — skipping integration tests.")


def _ffprobe_info(path: Path) -> dict:
    """Return frame count and FPS from ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return {}
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        return {}
    s = streams[0]
    nb_frames = int(s.get("nb_frames", 0))
    fps_str = s.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den)
    except Exception:
        fps = 0.0
    return {"nb_frames": nb_frames, "fps": fps}


def test_uncompressed_rtdose_to_mp4(tmp_path, ffmpeg_path):
    src = Path(pydicom.data.get_testdata_file("rtdose.dcm"))
    out = tmp_path / "rtdose.mp4"
    info = validate_and_load(src)

    result = convert(
        request=ConversionRequest(input_path=src, output_path=out, preset="compressed"),
        ffmpeg_path=ffmpeg_path,
    )

    assert result.success, f"Conversion failed: {result.error}"
    assert out.exists()
    assert out.stat().st_size > 0
    assert result.frames_written == info.num_frames


def test_jpeg_ybr_multiframe_to_mp4(tmp_path, ffmpeg_path):
    src = Path(pydicom.data.get_testdata_file("examples_ybr_color.dcm"))
    out = tmp_path / "ybr_color.mp4"
    info = validate_and_load(src)

    result = convert(
        request=ConversionRequest(input_path=src, output_path=out, preset="compressed"),
        ffmpeg_path=ffmpeg_path,
    )

    assert result.success, f"Conversion failed: {result.error}"
    assert out.exists()
    assert result.frames_written == info.num_frames


def test_rle_rgb_to_mp4(tmp_path, ffmpeg_path):
    src = Path(pydicom.data.get_testdata_file("SC_rgb_rle_2frame.dcm"))
    out = tmp_path / "rle.mp4"

    result = convert(
        request=ConversionRequest(input_path=src, output_path=out, preset="compressed"),
        ffmpeg_path=ffmpeg_path,
    )

    assert result.success, f"Conversion failed: {result.error}"
    assert out.exists()
    assert result.frames_written == 2


def test_cancel_leaves_no_partial_file(tmp_path, ffmpeg_path):
    import threading
    src = Path(pydicom.data.get_testdata_file("examples_ybr_color.dcm"))
    out = tmp_path / "cancelled.mp4"
    cancel = threading.Event()

    frame_count = [0]

    def progress_cb(cur, total):
        frame_count[0] = cur
        if cur >= 5:
            cancel.set()

    result = convert(
        request=ConversionRequest(input_path=src, output_path=out, preset="compressed"),
        ffmpeg_path=ffmpeg_path,
        progress_cb=progress_cb,
        cancel_event=cancel,
    )

    assert not out.exists(), "Partial output must be deleted on cancel."


def test_fps_matches_source(tmp_path, ffmpeg_path):
    src = Path(pydicom.data.get_testdata_file("rtdose.dcm"))
    out = tmp_path / "fps_check.mp4"

    result = convert(
        request=ConversionRequest(
            input_path=src, output_path=out,
            preset="compressed", fps_override=15.0,
        ),
        ffmpeg_path=ffmpeg_path,
    )

    assert result.success
    info = _ffprobe_info(out)
    if info.get("fps"):
        assert abs(info["fps"] - 15.0) < 0.1, f"Expected 15 fps, got {info['fps']}"
