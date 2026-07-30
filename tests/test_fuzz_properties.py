"""Property-based and regression tests for the fuzzed parsing surfaces.

These tests run inside the normal ``unittest`` suite. The deterministic cases
guard the specific non-finite regression that coverage-guided fuzzing surfaced
(``_first_int`` / ``_first_float`` overflowing on ``inf``), and the optional
Hypothesis cases reuse the exact invariant checkers from the Atheris harnesses
so the same properties are exercised without the native fuzzing engine.
"""

import math
import unittest

import media_shrinker

try:  # Hypothesis is an optional dev dependency; skip gracefully without it.
    from hypothesis import given, settings, HealthCheck
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - exercised only when hypothesis absent
    _HAS_HYPOTHESIS = False

    def given(*_args, **_kwargs):
        """Return a no-op decorator while the owning test class is skipped."""

        def decorator(func):
            return func

        return decorator

    def settings(*_args, **_kwargs):
        """Return a no-op decorator while the owning test class is skipped."""

        def decorator(func):
            return func

        return decorator

    class _MissingHealthCheck:
        too_slow = object()

    class _MissingStrategies:
        def __getattr__(self, _name):
            return self._strategy

        def _strategy(self, *_args, **_kwargs):
            return None

    HealthCheck = _MissingHealthCheck()
    st = _MissingStrategies()


class NonFiniteRegressionTests(unittest.TestCase):
    """Regression coverage for the non-finite ffprobe values fuzzing found.

    A large-exponent numeric field (valid JSON, e.g. ``1e999``) is parsed by
    ``json.loads`` into ``inf``; the numeric coercers must skip it instead of
    raising ``OverflowError``.
    """

    def test_first_int_skips_non_finite(self) -> None:
        self.assertIsNone(media_shrinker._first_int("1e999"))
        self.assertIsNone(media_shrinker._first_int(float("inf")))
        self.assertIsNone(media_shrinker._first_int(float("-inf")))
        self.assertIsNone(media_shrinker._first_int(float("nan")))

    def test_first_int_falls_through_to_next_value(self) -> None:
        self.assertEqual(media_shrinker._first_int(float("inf"), "42"), 42)

    def test_first_float_skips_non_finite(self) -> None:
        self.assertEqual(media_shrinker._first_float("1e999"), 0.0)
        self.assertEqual(media_shrinker._first_float(float("nan")), 0.0)
        self.assertEqual(media_shrinker._first_float(float("inf"), "1.5"), 1.5)

    def test_parse_probe_payload_rejects_infinite_duration(self) -> None:
        payload = {
            "streams": [{"codec_type": "audio", "duration": "1e999"}],
            "format": {"size": "1000"},
        }
        with self.assertRaises(media_shrinker.MediaShrinkerError):
            media_shrinker._parse_probe_payload(payload, __import__("pathlib").Path("x"), source_size=1000)


class ProbePayloadTypeGuardRegressionTests(unittest.TestCase):
    """`_parse_probe_payload` rejects non-object ffprobe shapes with MediaShrinkerError.

    ffprobe output is untrusted; a payload, ``streams`` list member, or format
    section that is not an object (and a ``streams`` value that is not a list)
    must raise the project error rather than an ``AttributeError`` from a bare
    ``.get()`` call. Both fuzz surfaces previously pre-shaped every member as a
    dict, which masked this crash.
    """

    _PATH = __import__("pathlib").Path("probe.bin")

    def test_non_object_payload_rejected(self) -> None:
        with self.assertRaises(media_shrinker.MediaShrinkerError):
            media_shrinker._parse_probe_payload("not-an-object", self._PATH, source_size=1000)

    def test_non_list_streams_rejected(self) -> None:
        with self.assertRaises(media_shrinker.MediaShrinkerError):
            media_shrinker._parse_probe_payload(
                {"streams": "oops"}, self._PATH, source_size=1000
            )

    def test_non_object_stream_only_has_no_audio(self) -> None:
        with self.assertRaises(media_shrinker.MediaShrinkerError):
            media_shrinker._parse_probe_payload(
                {"streams": ["junk", 5, None]}, self._PATH, source_size=1000
            )

    def test_non_object_stream_skipped_but_audio_parses(self) -> None:
        probe = media_shrinker._parse_probe_payload(
            {
                "streams": [
                    "junk",
                    {"codec_type": "audio", "duration": "12.5", "codec_name": "flac"},
                ],
                "format": {"size": "1000", "format_name": "flac"},
            },
            self._PATH,
            source_size=1000,
        )
        self.assertEqual(probe.audio_codec, "flac")
        self.assertGreater(probe.duration_seconds, 0)

    def test_non_object_format_rejected(self) -> None:
        with self.assertRaises(media_shrinker.MediaShrinkerError):
            media_shrinker._parse_probe_payload(
                {"streams": [{"codec_type": "audio", "duration": "10"}], "format": "oops"},
                self._PATH,
                source_size=1000,
            )


@unittest.skipUnless(_HAS_HYPOTHESIS, "hypothesis not installed")
class SilenceParserPropertyTests(unittest.TestCase):
    """`parse_silencedetect_intervals` never raises and yields ordered intervals."""

    @settings(max_examples=300, deadline=None)
    @given(st.text())
    def test_arbitrary_text_never_crashes(self, text: str) -> None:
        intervals = media_shrinker.parse_silencedetect_intervals(text)
        self.assertIsInstance(intervals, list)
        for interval in intervals:
            self.assertGreaterEqual(interval.start_seconds, 0.0)
            self.assertGreater(interval.end_seconds, interval.start_seconds)

    @settings(max_examples=300, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.floats(min_value=0, max_value=1e6, allow_nan=False),
                st.floats(min_value=0, max_value=1e6, allow_nan=False),
            ),
            max_size=20,
        )
    )
    def test_synthesised_ffmpeg_log(self, pairs) -> None:
        lines = []
        for start, end in pairs:
            lines.append(f"[silencedetect @ 0x1] silence_start: {start}")
            lines.append(f"[silencedetect @ 0x1] silence_end: {end}")
        intervals = media_shrinker.parse_silencedetect_intervals("\n".join(lines))
        for interval in intervals:
            self.assertGreater(interval.end_seconds, interval.start_seconds)


@unittest.skipUnless(_HAS_HYPOTHESIS, "hypothesis not installed")
class ProbePayloadPropertyTests(unittest.TestCase):
    """`_parse_probe_payload` returns a valid probe or a domain error only."""

    _scalar = st.one_of(
        st.none(),
        st.just("N/A"),
        st.text(max_size=8),
        st.integers(min_value=-(10**9), max_value=10**12),
        st.floats(allow_nan=True, allow_infinity=True),
    )

    @settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(data=st.data())
    def test_arbitrary_payload(self, data) -> None:
        from pathlib import Path

        stream = st.fixed_dictionaries(
            {
                "codec_type": st.sampled_from([None, "audio", "video", "data", ""]),
                "codec_name": st.sampled_from([None, "flac", "opus", "aac", ""]),
                "duration": self._scalar,
                "bit_rate": self._scalar,
            }
        )
        # Un-masked: a stream member, the streams value, the format section, and
        # the whole payload may each be a non-object, so the parser's type guards
        # are actually exercised instead of pre-shaped away.
        stream_member = st.one_of(stream, self._scalar, st.lists(self._scalar, max_size=2))
        streams_value = st.one_of(self._scalar, st.lists(stream_member, max_size=4))
        format_value = st.one_of(
            self._scalar,
            st.fixed_dictionaries(
                {
                    "duration": self._scalar,
                    "size": self._scalar,
                    "bit_rate": self._scalar,
                    "format_name": st.sampled_from([None, "wav", "flac", ""]),
                }
            ),
        )
        payload = data.draw(
            st.one_of(
                self._scalar,
                st.fixed_dictionaries({"streams": streams_value, "format": format_value}),
            )
        )
        try:
            probe = media_shrinker._parse_probe_payload(
                payload, Path("probe.bin"), source_size=4096
            )
        except media_shrinker.MediaShrinkerError:
            return
        self.assertGreater(probe.duration_seconds, 0)
        self.assertTrue(math.isfinite(probe.duration_seconds))
        self.assertIsInstance(probe.size_bytes, int)


@unittest.skipUnless(_HAS_HYPOTHESIS, "hypothesis not installed")
class BuildSegmentsPropertyTests(unittest.TestCase):
    """`build_segments` returns a contiguous, gap-free plan covering the source."""

    @settings(max_examples=400, deadline=None)
    @given(
        duration=st.floats(min_value=0.001, max_value=5000, allow_nan=False),
        max_segment=st.floats(min_value=50, max_value=10000, allow_nan=False),
        intervals=st.lists(
            st.tuples(
                st.floats(min_value=0, max_value=5000, allow_nan=False),
                st.floats(min_value=0.001, max_value=5000, allow_nan=False),
            ),
            max_size=8,
        ),
    )
    def test_plan_covers_source(self, duration, max_segment, intervals) -> None:
        silence = [
            media_shrinker.SilenceInterval(start_seconds=s, end_seconds=s + length)
            for s, length in intervals
        ]
        segments = media_shrinker.build_segments(
            duration_seconds=duration,
            max_segment_duration_seconds=max_segment,
            silence_intervals=silence,
        )
        self.assertTrue(segments)
        total = len(segments)
        cursor = 0.0
        for index, segment in enumerate(segments, start=1):
            self.assertEqual(segment.index, index)
            self.assertEqual(segment.total_segments, total)
            self.assertGreater(segment.duration_seconds, 0.0)
            self.assertLessEqual(segment.duration_seconds, max_segment + 1e-3)
            self.assertAlmostEqual(segment.start_seconds, cursor, delta=1e-3)
            cursor = segment.start_seconds + segment.duration_seconds
        self.assertAlmostEqual(cursor, duration, delta=1e-3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
