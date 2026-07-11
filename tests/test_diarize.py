"""Tests for the optional speaker-diarization hook (diarize.py).

All tests run offline: backends are injected fakes, and the unavailable
path is exercised by blocking the optional import via sys.modules. No
model download or network access ever happens here.
"""

import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import diarize
from diarize import (
    AttributedSegment,
    DiarizationResult,
    DiarizationUnavailableError,
    SpeakerTurn,
    diarize_file,
    merge_with_transcript,
    to_text,
)


@dataclass
class FakeSegment:
    """Duck-typed transcript segment with .start/.end/.text attributes."""

    start: float
    end: float
    text: str


class TestImportIsLight(unittest.TestCase):
    """Importing diarize must not drag in the optional heavy dependency."""

    def test_pyannote_not_imported_by_module_import(self):
        self.assertIn("diarize", sys.modules)
        self.assertNotIn("pyannote.audio", sys.modules)


class TestDiarizeFileWithInjectedBackend(unittest.TestCase):
    """diarize_file with a fake backend: no model, no network."""

    def test_returns_result_with_turns_and_speaker_count(self):
        def backend(audio_path):
            self.assertEqual(audio_path, "meeting.wav")
            return [
                SpeakerTurn(0.0, 2.0, "SPEAKER_00"),
                SpeakerTurn(2.0, 4.0, "SPEAKER_01"),
                SpeakerTurn(4.0, 6.0, "SPEAKER_00"),
            ]

        result = diarize_file("meeting.wav", backend=backend)
        self.assertIsInstance(result, DiarizationResult)
        self.assertEqual(len(result.turns), 3)
        self.assertEqual(result.speaker_count, 2)

    def test_turns_are_sorted_by_start_time(self):
        def backend(_):
            return [
                SpeakerTurn(5.0, 6.0, "B"),
                SpeakerTurn(0.0, 1.0, "A"),
                SpeakerTurn(2.0, 3.0, "C"),
            ]

        result = diarize_file("x.wav", backend=backend)
        self.assertEqual([t.start for t in result.turns], [0.0, 2.0, 5.0])

    def test_empty_backend_output(self):
        result = diarize_file("silent.wav", backend=lambda _: [])
        self.assertEqual(result.turns, ())
        self.assertEqual(result.speaker_count, 0)

    def test_backend_may_return_any_iterable(self):
        result = diarize_file(
            "gen.wav",
            backend=lambda _: iter([SpeakerTurn(0.0, 1.0, "S")]),
        )
        self.assertEqual(result.speaker_count, 1)


class TestDefaultBackendUnavailable(unittest.TestCase):
    """Without pyannote.audio installed, the error must be clear and actionable."""

    def _call_with_import_blocked(self):
        blocked = {"pyannote": None, "pyannote.audio": None}
        with patch.dict(sys.modules, blocked):
            diarize_file("audio.wav")

    def test_raises_diarization_unavailable_error(self):
        with self.assertRaises(DiarizationUnavailableError):
            self._call_with_import_blocked()

    def test_error_message_is_actionable(self):
        with self.assertRaises(DiarizationUnavailableError) as ctx:
            self._call_with_import_blocked()
        message = str(ctx.exception)
        self.assertIn("pip install pyannote.audio", message)
        self.assertIn("backend", message)

    def test_error_chains_the_original_import_error(self):
        with self.assertRaises(DiarizationUnavailableError) as ctx:
            self._call_with_import_blocked()
        self.assertIsInstance(ctx.exception.__cause__, ImportError)


class TestDefaultBackendSuccess(unittest.TestCase):
    """The default pyannote adapter is covered with local fakes."""

    def test_default_backend_converts_annotation_tracks(self):
        testcase = self

        class FakeTimelineSegment:
            start = 1.25
            end = 2.5

        class FakeAnnotation:
            def itertracks(self, *, yield_label=False):
                testcase.assertTrue(yield_label)
                yield FakeTimelineSegment(), None, "SPEAKER_X"

        class FakePipeline:
            @classmethod
            def from_pretrained(cls, name):
                testcase.assertEqual(name, diarize.DEFAULT_PIPELINE_NAME)
                return cls()

            def __call__(self, audio_path):
                testcase.assertEqual(audio_path, "audio.wav")
                return FakeAnnotation()

        pyannote_module = types.ModuleType("pyannote")
        audio_module = types.ModuleType("pyannote.audio")
        audio_module.Pipeline = FakePipeline
        with patch.dict(
            sys.modules,
            {"pyannote": pyannote_module, "pyannote.audio": audio_module},
        ):
            turns = diarize._default_backend("audio.wav")

        self.assertEqual(turns, [SpeakerTurn(1.25, 2.5, "SPEAKER_X")])


class TestMergeWithTranscript(unittest.TestCase):
    """Pure overlap-based speaker assignment."""

    def test_exact_overlap_assignment(self):
        turns = [
            SpeakerTurn(0.0, 5.0, "SPEAKER_00"),
            SpeakerTurn(5.0, 10.0, "SPEAKER_01"),
        ]
        segments = [
            FakeSegment(0.0, 5.0, "hello"),
            FakeSegment(5.0, 10.0, "world"),
        ]
        merged = merge_with_transcript(turns, segments)
        self.assertEqual([m.speaker for m in merged], ["SPEAKER_00", "SPEAKER_01"])
        self.assertEqual([m.text for m in merged], ["hello", "world"])

    def test_partial_overlap_picks_max_overlap_speaker(self):
        turns = [
            SpeakerTurn(0.0, 4.0, "SPEAKER_00"),
            SpeakerTurn(4.0, 10.0, "SPEAKER_01"),
        ]
        # Segment spans 3..9: 1s with SPEAKER_00, 5s with SPEAKER_01.
        merged = merge_with_transcript(turns, [FakeSegment(3.0, 9.0, "mixed")])
        self.assertEqual(merged[0].speaker, "SPEAKER_01")

    def test_no_overlap_falls_back_to_speaker_1(self):
        turns = [SpeakerTurn(0.0, 1.0, "SPEAKER_00")]
        merged = merge_with_transcript(turns, [FakeSegment(50.0, 55.0, "late")])
        self.assertEqual(merged[0].speaker, "SPEAKER_1")

    def test_empty_turns_falls_back_to_speaker_1(self):
        merged = merge_with_transcript([], [FakeSegment(0.0, 1.0, "solo")])
        self.assertEqual(merged[0].speaker, "SPEAKER_1")

    def test_touching_boundary_is_not_overlap(self):
        turns = [SpeakerTurn(0.0, 2.0, "SPEAKER_00")]
        merged = merge_with_transcript(turns, [FakeSegment(2.0, 4.0, "after")])
        self.assertEqual(merged[0].speaker, "SPEAKER_1")

    def test_multi_speaker_accumulates_split_turns(self):
        # SPEAKER_00 overlaps in two short turns (1s + 2s = 3s total),
        # SPEAKER_01 overlaps once for 2.5s; accumulation must win for 00.
        turns = [
            SpeakerTurn(0.0, 1.0, "SPEAKER_00"),
            SpeakerTurn(1.0, 3.5, "SPEAKER_01"),
            SpeakerTurn(3.5, 5.5, "SPEAKER_00"),
        ]
        merged = merge_with_transcript(turns, [FakeSegment(0.0, 5.5, "debate")])
        self.assertEqual(merged[0].speaker, "SPEAKER_00")

    def test_multiple_segments_multi_speaker(self):
        turns = [
            SpeakerTurn(0.0, 3.0, "A"),
            SpeakerTurn(3.0, 6.0, "B"),
            SpeakerTurn(6.0, 9.0, "C"),
        ]
        segments = [
            FakeSegment(0.5, 2.5, "one"),
            FakeSegment(3.5, 5.5, "two"),
            FakeSegment(6.5, 8.5, "three"),
        ]
        merged = merge_with_transcript(turns, segments)
        self.assertEqual([m.speaker for m in merged], ["A", "B", "C"])

    def test_preserves_segment_order_and_fields(self):
        turns = [SpeakerTurn(0.0, 10.0, "S")]
        segments = [FakeSegment(1.0, 2.0, "first"), FakeSegment(3.0, 4.0, "second")]
        merged = merge_with_transcript(turns, segments)
        self.assertEqual(merged[0].start, 1.0)
        self.assertEqual(merged[0].end, 2.0)
        self.assertEqual([m.text for m in merged], ["first", "second"])

    def test_empty_segments_returns_empty_list(self):
        self.assertEqual(merge_with_transcript([SpeakerTurn(0, 1, "S")], []), [])


class TestToText(unittest.TestCase):
    """Rendering attributed segments as '[speaker] text' lines."""

    def test_formats_speaker_prefixed_lines(self):
        merged = [
            AttributedSegment(0.0, 1.0, "hello there", "SPEAKER_00"),
            AttributedSegment(1.0, 2.0, "hi back", "SPEAKER_01"),
        ]
        self.assertEqual(
            to_text(merged),
            "[SPEAKER_00] hello there\n[SPEAKER_01] hi back",
        )

    def test_empty_input_yields_empty_string(self):
        self.assertEqual(to_text([]), "")

    def test_round_trip_with_merge(self):
        turns = [SpeakerTurn(0.0, 2.0, "SPEAKER_00")]
        merged = merge_with_transcript(turns, [FakeSegment(0.0, 2.0, "solo line")])
        self.assertEqual(to_text(merged), "[SPEAKER_00] solo line")


class TestModuleConstants(unittest.TestCase):
    """Public constants exposed for callers."""

    def test_fallback_speaker_constant(self):
        self.assertEqual(diarize.FALLBACK_SPEAKER, "SPEAKER_1")


if __name__ == "__main__":
    unittest.main()
