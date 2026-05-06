"""Unit tests for the FPS resolution chain."""

import numpy as np
import pydicom
import pytest

from src.core.fps_resolver import DEFAULT_FPS, FpsResult, resolve_fps


def _ds(**kwargs) -> pydicom.Dataset:
    ds = pydicom.Dataset()
    for k, v in kwargs.items():
        setattr(ds, k, v)
    return ds


def test_user_override_takes_priority():
    ds = _ds(CineRate=15, FrameTime=100)
    result = resolve_fps(ds, user_override=24.0)
    assert result.fps == 24.0
    assert result.source == "user_override"


def test_cine_rate_used_first():
    ds = _ds(CineRate=30, FrameTime=50)
    result = resolve_fps(ds)
    assert result.fps == 30.0
    assert result.source == "CineRate"


def test_recommended_display_frame_rate():
    ds = _ds(RecommendedDisplayFrameRate=25)
    result = resolve_fps(ds)
    assert result.fps == 25.0
    assert result.source == "RecommendedDisplayFrameRate"


def test_frame_time():
    ds = _ds(FrameTime=33.33)
    result = resolve_fps(ds)
    assert abs(result.fps - 1000.0 / 33.33) < 0.01
    assert result.source == "FrameTime"


def test_frame_time_vector_uniform():
    ds = _ds(FrameTimeVector=[33.33, 33.33, 33.33])
    result = resolve_fps(ds)
    assert abs(result.fps - 1000.0 / 33.33) < 0.01
    assert result.source == "FrameTimeVector"
    assert result.warning == ""


def test_frame_time_vector_non_uniform_warns():
    ds = _ds(FrameTimeVector=[30.0, 60.0, 90.0])
    result = resolve_fps(ds)
    assert result.fps > 0
    assert result.source == "FrameTimeVector"
    assert "non-uniform" in result.warning.lower()


def test_default_fallback():
    ds = pydicom.Dataset()
    result = resolve_fps(ds)
    assert result.fps == DEFAULT_FPS
    assert result.source == "default_fallback"
    assert result.warning != ""


def test_cine_rate_zero_skipped():
    ds = _ds(CineRate=0, FrameTime=40)
    result = resolve_fps(ds)
    assert result.source == "FrameTime"


def test_user_override_zero_ignored():
    ds = _ds(CineRate=15)
    result = resolve_fps(ds, user_override=0.0)
    assert result.source == "CineRate"
