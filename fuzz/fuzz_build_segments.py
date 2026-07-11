#!/usr/bin/env python3
"""Atheris fuzz harness for ``media_shrinker.build_segments``.

``build_segments`` is the duration/silence "assembler": given a source
duration, a maximum segment length, and detected silence intervals (all
derived from untrusted media), it produces the split plan that drives ffmpeg.
A broken plan means dropped or duplicated audio, so this harness fuzzes the
inputs and asserts the structural invariants of a valid split plan:

* segments are contiguous and start at 0,
* they exactly cover ``[0, duration]`` (no gaps, no overlap),
* every segment is non-empty and shorter than the configured maximum,
* ``index`` / ``total_segments`` bookkeeping is internally consistent.

Malformed inputs are expected to raise ``ValueError`` (a documented guard);
any other exception is a defect.

Run locally (Python 3.8 - 3.12)::

    python fuzz/fuzz_build_segments.py -atheris_runs=200000 fuzz/corpus/build_segments
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media_shrinker  # noqa: E402

_TOLERANCE = 1e-3


def check_invariants(duration, max_segment, intervals) -> None:
    """Assert ``build_segments`` returns a well-formed, gap-free split plan."""
    try:
        segments = media_shrinker.build_segments(
            duration_seconds=duration,
            max_segment_duration_seconds=max_segment,
            silence_intervals=intervals,
        )
    except ValueError:
        return  # documented guard for non-positive inputs

    assert isinstance(segments, list) and segments
    total = len(segments)
    expected_start = 0.0
    for index, segment in enumerate(segments, start=1):
        assert segment.index == index
        assert segment.total_segments == total
        assert segment.duration_seconds > 0.0
        assert segment.duration_seconds <= max_segment + _TOLERANCE
        assert abs(segment.start_seconds - expected_start) <= _TOLERANCE
        expected_start = segment.start_seconds + segment.duration_seconds
    # The plan must cover the whole source with no gap or overrun.
    assert abs(expected_start - duration) <= _TOLERANCE


# Realistic domains keep the invariant meaningful and the harness fast. The
# maximum-duration cap is a bounded CLI value (default 4h), so a sub-second cap
# against a multi-day source — which would demand billions of segments — is not
# a real input. Bounding both to millisecond resolution keeps the segment count
# small while still exercising multi-window splitting and silence selection, and
# avoids float-precision corners (e.g. duration == max == DBL_MAX) unreachable
# for real audio.
_MAX_DURATION_MS = 5_000_000  # 5,000 seconds (~83min)
_MIN_SEGMENT_MS = 50_000  # 50 seconds -> at most ~100 segments
_MAX_SEGMENT_MS = 10_000_000  # 10,000 seconds


def _consume_intervals(fdp, duration):
    """Build a list of ordered, non-negative silence intervals from bytes."""
    intervals = []
    span_ms = max(1, int(duration * 1000))
    for _ in range(fdp.ConsumeIntInRange(0, 6)):
        start = fdp.ConsumeIntInRange(0, span_ms) / 1000.0
        length = fdp.ConsumeIntInRange(1, span_ms) / 1000.0
        intervals.append(
            media_shrinker.SilenceInterval(
                start_seconds=start, end_seconds=start + length
            )
        )
    return intervals


def test_one_input(data: bytes) -> None:
    """Derive positive durations and intervals from bytes, then check."""
    import atheris

    fdp = atheris.FuzzedDataProvider(data)
    duration = fdp.ConsumeIntInRange(0, _MAX_DURATION_MS) / 1000.0
    max_segment = fdp.ConsumeIntInRange(_MIN_SEGMENT_MS, _MAX_SEGMENT_MS) / 1000.0
    intervals = _consume_intervals(fdp, duration)
    check_invariants(duration, max_segment, intervals)


def main() -> None:
    """Entry point that wires the harness into libFuzzer via Atheris."""
    import atheris

    atheris.instrument_all()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
