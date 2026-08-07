#!/usr/bin/env python3
"""Deterministic overlap-window planning for long-form audio processing."""

from __future__ import annotations

from speaker_timeline_types import ChunkWindow, _require_finite


def plan_overlapping_chunks(
    duration_seconds: float,
    *,
    window_seconds: float = 180.0,
    overlap_seconds: float = 10.0,
) -> tuple[ChunkWindow, ...]:
    """Plan gap-free long-form windows with deterministic overlap.

    Args:
        duration_seconds: Positive finite recording duration.
        window_seconds: Positive finite maximum chunk duration.
        overlap_seconds: Non-negative overlap strictly smaller than the window.

    Returns:
        Ordered :class:`ChunkWindow` values covering the entire recording.

    Raises:
        ValueError: If the duration or window geometry is invalid.
    """
    _require_finite(duration_seconds, "duration_seconds")
    _require_finite(window_seconds, "window_seconds")
    _require_finite(overlap_seconds, "overlap_seconds")
    if duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be greater than zero")
    if window_seconds <= 0.0:
        raise ValueError("window_seconds must be greater than zero")
    if overlap_seconds < 0.0:
        raise ValueError("overlap_seconds must be greater than or equal to zero")
    if overlap_seconds >= window_seconds:
        raise ValueError("overlap_seconds must be smaller than window_seconds")

    step = window_seconds - overlap_seconds
    windows: list[ChunkWindow] = []
    start = 0.0
    index = 1
    while True:
        end = min(duration_seconds, start + window_seconds)
        windows.append(ChunkWindow(f"chunk_{index:04d}", start, end))
        if end >= duration_seconds:
            break
        start += step
        index += 1
    return tuple(windows)
