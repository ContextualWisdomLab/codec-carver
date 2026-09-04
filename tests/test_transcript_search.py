"""Tests for the fail-closed transcript-search boundary."""

import json
import tempfile
import unittest
from pathlib import Path

from transcript_search import (
    SearchPolicyUnavailable,
    Segment,
    TranscriptIndex,
    load_transcript_json,
    tokenize,
)


class TokenizeTest(unittest.TestCase):
    """Semantic tokenization is unavailable without validated evidence."""

    def test_empty_text_is_identity_case(self):
        self.assertEqual(tokenize(""), [])

    def test_nonempty_text_fails_closed(self):
        with self.assertRaises(SearchPolicyUnavailable):
            tokenize("Hello, WORLD!")


class SearchTest(unittest.TestCase):
    """Storage remains lossless while retrieval selection is disabled."""

    def test_add_preserves_segment_count_without_deriving_scores(self):
        index = TranscriptIndex()
        added = index.add(
            "recording",
            [
                Segment(0.0, 1.0, "alpha alpha beta"),
                Segment(1.0, 2.0, "beta gamma"),
            ],
        )
        self.assertEqual(added, 2)
        self.assertEqual(len(index), 2)

    def test_nonempty_query_fails_closed(self):
        index = TranscriptIndex()
        index.add("recording", [Segment(0.0, 1.0, "alpha")])
        with self.assertRaisesRegex(
            SearchPolicyUnavailable,
            "validated, research-backed retrieval and evaluation contract",
        ):
            index.search("alpha")

    def test_empty_query_is_rejected_without_selection(self):
        with self.assertRaises(ValueError):
            TranscriptIndex().search("")

    def test_add_accepts_mapping_segments(self):
        index = TranscriptIndex()
        added = index.add(
            "dict-rec", [{"start": 1.0, "end": 2.0, "text": "mapping works"}]
        )
        self.assertEqual(added, 1)
        self.assertEqual(len(index), 1)

    def test_add_rejects_segment_missing_field(self):
        index = TranscriptIndex()
        with self.assertRaises(TypeError):
            index.add("bad", [{"start": 0.0, "end": 1.0}])

    def test_add_rejects_object_missing_attribute(self):
        class MissingText:
            start = 0.0
            end = 1.0

        index = TranscriptIndex()
        with self.assertRaises(TypeError) as ctx:
            index.add("bad", [MissingText()])
        self.assertIn("attribute", str(ctx.exception))


class LoadTranscriptJsonTest(unittest.TestCase):
    """Reading transcription sidecars remains lossless and independently valid."""

    def test_roundtrip_from_tmp_file(self):
        payload = {
            "segments": [
                {"start": 0.0, "end": 3.2, "text": "Welcome to the meeting."},
                {"start": 3.2, "end": 9.9, "text": "We discussed the codec roadmap."},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recording.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            segments = load_transcript_json(path)

        self.assertEqual(
            segments,
            [
                Segment(0.0, 3.2, "Welcome to the meeting."),
                Segment(3.2, 9.9, "We discussed the codec roadmap."),
            ],
        )

    def test_rejects_non_sidecar_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(["not", "a", "sidecar"]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_transcript_json(path)

    def test_rejects_segment_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.json"
            path.write_text(
                json.dumps({"segments": [{"start": 0.0, "end": 1.0}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as ctx:
                load_transcript_json(path)
        self.assertIn("text", str(ctx.exception))

    def test_rejects_non_object_segment_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps({"segments": ["not-an-object"]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as ctx:
                load_transcript_json(path)
        self.assertIn("not an object", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
