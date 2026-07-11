"""Tests for silence-based chapter detection and export."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chapters import Chapter, detect_chapters, to_ffmetadata, to_json


@dataclass(frozen=True)
class FakeSilence:
    """Minimal duck-typed silence interval for the chapters contract."""

    start_seconds: float
    end_seconds: float


class DetectChaptersTest(unittest.TestCase):
    """Behavioural tests for detect_chapters."""

    def test_single_chapter_when_no_silences(self) -> None:
        """No silences yields one chapter covering the full duration."""

        chapters = detect_chapters([], total_duration=600.0)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].index, 1)
        self.assertEqual(chapters[0].start, 0.0)
        self.assertEqual(chapters[0].end, 600.0)
        self.assertEqual(chapters[0].title, "Chapter 1")

    def test_boundary_at_long_silence_midpoint(self) -> None:
        """A qualifying silence splits chapters at its midpoint."""

        silences = [FakeSilence(300.0, 310.0)]
        chapters = detect_chapters(silences, total_duration=600.0)
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].start, 0.0)
        self.assertEqual(chapters[0].end, 305.0)
        self.assertEqual(chapters[1].start, 305.0)
        self.assertEqual(chapters[1].end, 600.0)
        self.assertEqual(
            [c.title for c in chapters], ["Chapter 1", "Chapter 2"]
        )

    def test_short_silence_does_not_split(self) -> None:
        """Silences shorter than min_gap_seconds produce no boundary."""

        silences = [FakeSilence(300.0, 301.0)]
        chapters = detect_chapters(
            silences, total_duration=600.0, min_gap_seconds=3.0
        )
        self.assertEqual(len(chapters), 1)

    def test_short_chapter_merges_into_previous(self) -> None:
        """A too-short trailing chapter merges into its predecessor."""

        silences = [FakeSilence(300.0, 306.0), FakeSilence(580.0, 590.0)]
        chapters = detect_chapters(
            silences, total_duration=600.0, min_chapter_seconds=60.0
        )
        # The 585..600 chapter (15s) merges back into the previous one.
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].end, 303.0)
        self.assertEqual(chapters[1].start, 303.0)
        self.assertEqual(chapters[1].end, 600.0)

    def test_short_first_chapter_merges_forward(self) -> None:
        """A too-short first chapter merges into the following chapter."""

        silences = [FakeSilence(10.0, 20.0), FakeSilence(300.0, 310.0)]
        chapters = detect_chapters(
            silences, total_duration=600.0, min_chapter_seconds=60.0
        )
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].start, 0.0)
        self.assertEqual(chapters[0].end, 305.0)
        self.assertEqual(chapters[1].end, 600.0)

    def test_chapters_always_cover_full_duration(self) -> None:
        """First chapter starts at 0 and last ends at total_duration."""

        silences = [
            FakeSilence(100.0, 110.0),
            FakeSilence(250.0, 260.0),
            FakeSilence(400.0, 410.0),
        ]
        chapters = detect_chapters(silences, total_duration=500.0)
        self.assertEqual(chapters[0].start, 0.0)
        self.assertEqual(chapters[-1].end, 500.0)
        for previous, current in zip(chapters, chapters[1:]):
            self.assertEqual(previous.end, current.start)
        self.assertEqual([c.index for c in chapters], [1, 2, 3, 4])

    def test_silences_beyond_duration_are_clamped(self) -> None:
        """Silence spans past total_duration are clamped, not boundaries."""

        silences = [FakeSilence(590.0, 700.0), FakeSilence(650.0, 800.0)]
        chapters = detect_chapters(silences, total_duration=600.0)
        # Clamped span 590..600 has midpoint 595; the resulting 5s tail
        # chapter merges into the previous one, leaving a single chapter.
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].end, 600.0)

    def test_unsorted_and_overlapping_silences(self) -> None:
        """Unsorted, overlapping input is sorted and merged first."""

        silences = [
            FakeSilence(400.0, 410.0),
            FakeSilence(100.0, 106.0),
            FakeSilence(103.0, 108.0),
        ]
        chapters = detect_chapters(silences, total_duration=600.0)
        self.assertEqual(len(chapters), 3)
        # 100..108 merged span has midpoint 104.
        self.assertEqual(chapters[0].end, 104.0)
        self.assertEqual(chapters[1].end, 405.0)

    def test_zero_duration_raises(self) -> None:
        """A zero total_duration is rejected."""

        with self.assertRaises(ValueError):
            detect_chapters([], total_duration=0.0)

    def test_negative_duration_raises(self) -> None:
        """A negative total_duration is rejected."""

        with self.assertRaises(ValueError):
            detect_chapters([], total_duration=-5.0)

    def test_short_recording_is_single_chapter(self) -> None:
        """A recording shorter than min_chapter_seconds stays one chapter."""

        silences = [FakeSilence(10.0, 15.0)]
        chapters = detect_chapters(
            silences, total_duration=30.0, min_chapter_seconds=60.0
        )
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].end, 30.0)


class ExportTest(unittest.TestCase):
    """Tests for FFMETADATA and JSON serialization."""

    def test_ffmetadata_exact_format(self) -> None:
        """FFMETADATA output matches ffmpeg's expected layout exactly."""

        chapters = [
            Chapter(index=1, start=0.0, end=305.0, title="Chapter 1"),
            Chapter(index=2, start=305.0, end=600.5, title="Chapter 2"),
        ]
        expected = (
            ";FFMETADATA1\n"
            "\n"
            "[CHAPTER]\n"
            "TIMEBASE=1/1000\n"
            "START=0\n"
            "END=305000\n"
            "title=Chapter 1\n"
            "\n"
            "[CHAPTER]\n"
            "TIMEBASE=1/1000\n"
            "START=305000\n"
            "END=600500\n"
            "title=Chapter 2\n"
        )
        self.assertEqual(to_ffmetadata(chapters), expected)

    def test_ffmetadata_header_only_for_empty_list(self) -> None:
        """An empty chapter list still yields the FFMETADATA header."""

        self.assertEqual(to_ffmetadata([]), ";FFMETADATA1\n")

    def test_json_round_trip(self) -> None:
        """JSON output parses back into the same chapter fields."""

        chapters = detect_chapters(
            [FakeSilence(300.0, 310.0)], total_duration=600.0
        )
        payload = json.loads(to_json(chapters))
        self.assertEqual(
            payload,
            [
                {
                    "index": 1,
                    "start": 0.0,
                    "end": 305.0,
                    "title": "Chapter 1",
                },
                {
                    "index": 2,
                    "start": 305.0,
                    "end": 600.0,
                    "title": "Chapter 2",
                },
            ],
        )

    def test_end_to_end_pipeline(self) -> None:
        """detect_chapters output feeds directly into to_ffmetadata."""

        silences = [FakeSilence(120.0, 126.0), FakeSilence(360.0, 366.0)]
        chapters = detect_chapters(silences, total_duration=600.0)
        metadata = to_ffmetadata(chapters)
        self.assertTrue(metadata.startswith(";FFMETADATA1\n"))
        self.assertEqual(metadata.count("[CHAPTER]"), 3)
        self.assertIn("START=123000", metadata)
        self.assertIn("END=363000", metadata)


if __name__ == "__main__":
    unittest.main()
