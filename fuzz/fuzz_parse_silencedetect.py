#!/usr/bin/env python3
"""Atheris fuzz harness for ``media_shrinker.parse_silencedetect_intervals``.

``parse_silencedetect_intervals`` consumes the *stderr* of an external
``ffmpeg silencedetect`` run — untrusted, attacker-influenceable text (a
crafted media file can steer ffmpeg's log output). This harness feeds
arbitrary byte strings and asserts the parser never raises and only ever
produces well-formed, ordered silence intervals.

Run locally (Python 3.8 - 3.12)::

    python fuzz/fuzz_parse_silencedetect.py -atheris_runs=200000 fuzz/corpus/parse_silencedetect

The module is import-safe without Atheris so the invariant checker can be
reused from the plain-``pytest`` property suite.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media_shrinker  # noqa: E402


def check_invariants(stderr: str) -> None:
    """Assert ``parse_silencedetect_intervals`` output is well-formed.

    The parser must never raise on arbitrary text and every returned
    interval must be finite with ``0 <= start < end``.
    """
    intervals = media_shrinker.parse_silencedetect_intervals(stderr)
    assert isinstance(intervals, list)
    for interval in intervals:
        assert isinstance(interval, media_shrinker.SilenceInterval)
        assert math.isfinite(interval.start_seconds)
        assert math.isfinite(interval.end_seconds)
        assert interval.start_seconds >= 0.0
        assert interval.end_seconds > interval.start_seconds


def test_one_input(data: bytes) -> None:
    """Decode fuzzer bytes to text and run the invariant check."""
    # ffmpeg stderr reaches the parser as text; model arbitrary bytes by
    # decoding leniently (the real caller uses subprocess text mode).
    stderr = data.decode("utf-8", errors="replace")
    check_invariants(stderr)


def main() -> None:
    """Entry point that wires the harness into libFuzzer via Atheris."""
    import atheris

    atheris.instrument_all()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
