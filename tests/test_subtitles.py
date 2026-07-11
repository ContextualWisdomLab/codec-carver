"""Tests for the subtitle/caption export module."""

import tempfile
import unittest
from pathlib import Path

from subtitles import (
    Segment,
    to_srt,
    to_vtt,
    write_srt,
    write_vtt,
)


class TestToSrt(unittest.TestCase):
    """Tests for :func:`subtitles.to_srt`."""

    def test_empty_input_returns_empty_string(self):
        """An empty segment list produces an empty SubRip document."""
        self.assertEqual(to_srt([]), "")

    def test_single_segment_format(self):
        """A single cue is numbered 1 and uses comma-millisecond timestamps."""
        result = to_srt([Segment(0.0, 1.5, "Hello")])
        self.assertEqual(
            result,
            "1\n00:00:00,000 --> 00:00:01,500\nHello\n",
        )

    def test_sequential_indices(self):
        """Cues are numbered sequentially starting at 1."""
        segments = [
            Segment(0.0, 1.0, "one"),
            Segment(1.0, 2.0, "two"),
            Segment(2.0, 3.0, "three"),
        ]
        result = to_srt(segments)
        lines = result.splitlines()
        # Index lines appear at the start of each cue block.
        self.assertEqual(lines[0], "1")
        self.assertEqual(lines[4], "2")
        self.assertEqual(lines[8], "3")

    def test_sub_second_timestamps(self):
        """Fractional seconds are rendered as milliseconds."""
        result = to_srt([Segment(0.001, 0.25, "x")])
        self.assertIn("00:00:00,001 --> 00:00:00,250", result)

    def test_hour_plus_timestamp(self):
        """Offsets beyond one hour populate the hours field."""
        # 3661.789s == 01:01:01.789
        result = to_srt([Segment(3661.789, 3662.0, "later")])
        self.assertIn("01:01:01,789 --> 01:01:02,000", result)

    def test_multi_line_text_preserved(self):
        """Newlines within caption text are preserved in the cue body."""
        result = to_srt([Segment(0.0, 1.0, "line one\nline two")])
        self.assertIn("line one\nline two", result)

    def test_uses_comma_separator_not_period(self):
        """SubRip must use a comma before the milliseconds field."""
        result = to_srt([Segment(0.0, 1.0, "x")])
        self.assertIn("00:00:00,000", result)
        self.assertNotIn("00:00:00.000", result)

    def test_cues_separated_by_blank_line(self):
        """Consecutive cues are separated by exactly one blank line."""
        result = to_srt([Segment(0.0, 1.0, "a"), Segment(1.0, 2.0, "b")])
        self.assertIn("\na\n\n2\n", result)


class TestToVtt(unittest.TestCase):
    """Tests for :func:`subtitles.to_vtt`."""

    def test_empty_input_still_has_header(self):
        """Even with no cues the WEBVTT header is emitted."""
        self.assertEqual(to_vtt([]), "WEBVTT\n")

    def test_header_present(self):
        """A populated document begins with the WEBVTT header."""
        result = to_vtt([Segment(0.0, 1.0, "hi")])
        self.assertTrue(result.startswith("WEBVTT\n\n"))

    def test_single_segment_format(self):
        """WebVTT cues use period-millisecond timestamps and no index."""
        result = to_vtt([Segment(0.0, 1.5, "Hello")])
        self.assertEqual(
            result,
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello\n",
        )

    def test_uses_period_separator_not_comma(self):
        """WebVTT must use a period before the milliseconds field."""
        result = to_vtt([Segment(0.0, 1.0, "x")])
        self.assertIn("00:00:00.000", result)
        self.assertNotIn("00:00:00,000", result)

    def test_hour_plus_timestamp(self):
        """Offsets beyond one hour populate the hours field."""
        result = to_vtt([Segment(3661.789, 3662.0, "later")])
        self.assertIn("01:01:01.789 --> 01:01:02.000", result)

    def test_no_sequential_index_lines(self):
        """WebVTT cues are not prefixed with numeric indices."""
        result = to_vtt([Segment(0.0, 1.0, "a"), Segment(1.0, 2.0, "b")])
        # The line immediately after the blank header line is a timestamp.
        lines = result.splitlines()
        self.assertEqual(lines[0], "WEBVTT")
        self.assertEqual(lines[1], "")
        self.assertIn("-->", lines[2])


class TestTimestampEdgeCases(unittest.TestCase):
    """Edge-case tests for timestamp formatting."""

    def test_negative_time_clamped_to_zero(self):
        """Negative offsets are clamped rather than producing bad output."""
        result = to_srt([Segment(-5.0, 1.0, "x")])
        self.assertIn("00:00:00,000 --> 00:00:01,000", result)

    def test_millisecond_rounding(self):
        """Values are rounded to the nearest whole millisecond."""
        # 1.0004s rounds to 000ms, 1.0006s rounds to 001ms.
        self.assertIn("00:00:01,000", to_srt([Segment(1.0004, 2.0, "a")]))
        self.assertIn("00:00:01,001", to_srt([Segment(1.0006, 2.0, "a")]))

    def test_crlf_normalized(self):
        """Windows line endings in text are normalized to newlines."""
        result = to_srt([Segment(0.0, 1.0, "a\r\nb")])
        self.assertIn("a\nb", result)
        self.assertNotIn("\r", result)

    def test_duck_typed_object_accepted(self):
        """Any object with start/end/text attributes works."""

        class Cue:
            """Minimal duck-typed segment stand-in."""

            start = 0.0
            end = 1.0
            text = "duck"

        result = to_srt([Cue()])
        self.assertIn("duck", result)
        self.assertIn("00:00:00,000 --> 00:00:01,000", result)


class TestFileWriters(unittest.TestCase):
    """Tests for the file-writing helpers."""

    def test_write_srt_roundtrip(self):
        """write_srt writes exactly what to_srt produces."""
        segments = [Segment(0.0, 1.0, "hi")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.srt"
            returned = write_srt(segments, path)
            self.assertEqual(returned, path)
            self.assertEqual(path.read_text(encoding="utf-8"), to_srt(segments))

    def test_write_vtt_roundtrip(self):
        """write_vtt writes exactly what to_vtt produces."""
        segments = [Segment(0.0, 1.0, "hi")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.vtt"
            returned = write_vtt(segments, path)
            self.assertEqual(returned, path)
            self.assertEqual(path.read_text(encoding="utf-8"), to_vtt(segments))

    def test_write_srt_accepts_string_path(self):
        """A string path is accepted and returned as a Path."""
        with tempfile.TemporaryDirectory() as tmp:
            path_str = str(Path(tmp) / "out.srt")
            returned = write_srt([Segment(0.0, 1.0, "x")], path_str)
            self.assertTrue(returned.exists())


if __name__ == "__main__":
    unittest.main()
