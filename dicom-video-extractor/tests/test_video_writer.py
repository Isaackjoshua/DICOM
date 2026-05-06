"""Tests for FFmpeg codec arg building and binary detection."""

import pytest

from src.utils.ffmpeg_utils import get_codec_args, locate_ffmpeg, probe_ffmpeg
from src.utils.exceptions import FFmpegNotFoundError


def test_codec_args_lossless_mp4():
    args = get_codec_args("lossless", "mp4", is_grayscale=False)
    assert "-crf" in args
    assert "0" in args


def test_codec_args_grayscale_lossless_avoids_yuv420p():
    args = get_codec_args("lossless", "mp4", is_grayscale=True)
    assert "yuv420p" not in args


def test_codec_args_compressed_mp4():
    args = get_codec_args("compressed", "mp4", is_grayscale=False)
    assert "libx264" in args


def test_codec_args_unknown_preset_falls_back():
    args = get_codec_args("banana", "mp4", is_grayscale=False)
    assert args  # should not crash, returns high-preset args


def test_locate_ffmpeg_or_skip():
    try:
        path = locate_ffmpeg()
        assert path
    except FFmpegNotFoundError:
        pytest.skip("FFmpeg not installed in test environment.")


def test_probe_ffmpeg_or_skip():
    try:
        info = probe_ffmpeg()
        assert info.version
        assert info.path
    except FFmpegNotFoundError:
        pytest.skip("FFmpeg not installed in test environment.")
