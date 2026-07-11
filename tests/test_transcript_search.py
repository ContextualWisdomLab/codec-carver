"""Tests for transcript_search: inverted index over timestamped transcripts."""

import json
import tempfile
import unittest
from pathlib import Path

from transcript_search import (
    Match,
    Segment,
    TranscriptIndex,
    load_transcript_json,
    tokenize,
)


def _make_index():
    """Build a small two-recording index used by several tests."""
    idx = TranscriptIndex()
    idx.add(
        "standup-monday",
        [
            Segment(0.0, 4.5, "Good morning, let's start the standup."),
            Segment(4.5, 12.0, "The codec budget is over by two megabytes."),
            Segment(12.0, 20.0, "Codec, codec, codec — we keep saying codec."),
        ],
    )
    idx.add(
        "retro-friday",
        [
            Segment(0.0, 6.0, "Retro time: what went well this sprint?"),
            Segment(6.0, 15.0, "The budget discussion about the codec dragged."),
        ],
    )
    return idx


class TokenizeTest(unittest.TestCase):
    """Behavior of the shared tokenizer."""

    def test_lowercases_and_strips_punctuation(self):
        """Tokens are case-folded and punctuation is dropped."""
        self.assertEqual(tokenize("Hello, WORLD! It's fine."), ["hello", "world", "it", "s", "fine"])

    def test_empty_text_yields_no_tokens(self):
        """Empty and punctuation-only strings produce no tokens."""
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("... !!! ???"), [])


class SearchTest(unittest.TestCase):
    """Indexing and search semantics."""

    def test_hit_carries_correct_timestamps_and_recording(self):
        """A match reports the recording id and the segment's start/end."""
        idx = _make_index()
        matches = idx.search("budget megabytes")
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertIsInstance(match, Match)
        self.assertEqual(match.recording_id, "standup-monday")
        self.assertEqual(match.start, 4.5)
        self.assertEqual(match.end, 12.0)
        self.assertIn("codec budget", match.text)

    def test_multi_word_query_uses_and_semantics(self):
        """Only segments containing every query term match."""
        idx = _make_index()
        # "budget" appears in two recordings, "dragged" in only one.
        matches = idx.search("budget dragged")
        self.assertEqual([m.recording_id for m in matches], ["retro-friday"])

    def test_ranking_by_term_frequency(self):
        """Segments with more query-term occurrences rank first."""
        idx = _make_index()
        matches = idx.search("codec")
        self.assertEqual(len(matches), 3)
        # The codec-codec-codec segment (tf=4) must outrank single mentions.
        self.assertEqual(matches[0].start, 12.0)
        self.assertEqual(matches[0].recording_id, "standup-monday")
        self.assertEqual(matches[0].score, 4)
        self.assertGreaterEqual(matches[0].score, matches[1].score)
        self.assertGreaterEqual(matches[1].score, matches[2].score)

    def test_ties_break_by_recording_then_time(self):
        """Equal scores sort by recording id, then start time ascending."""
        idx = TranscriptIndex()
        idx.add("b-rec", [Segment(5.0, 6.0, "alpha"), Segment(1.0, 2.0, "alpha")])
        idx.add("a-rec", [Segment(9.0, 10.0, "alpha")])
        matches = idx.search("alpha")
        self.assertEqual(
            [(m.recording_id, m.start) for m in matches],
            [("a-rec", 9.0), ("b-rec", 1.0), ("b-rec", 5.0)],
        )

    def test_search_is_case_insensitive(self):
        """Query case and transcript case are both irrelevant."""
        idx = _make_index()
        upper = idx.search("CODEC BUDGET")
        lower = idx.search("codec budget")
        self.assertEqual(upper, lower)
        self.assertEqual(len(lower), 2)

    def test_punctuation_in_query_is_ignored(self):
        """Punctuation around query words does not affect matching."""
        idx = _make_index()
        self.assertEqual(idx.search("codec!!!"), idx.search("codec"))

    def test_empty_query_raises_value_error(self):
        """Empty or punctuation-only queries raise ValueError."""
        idx = _make_index()
        with self.assertRaises(ValueError):
            idx.search("")
        with self.assertRaises(ValueError):
            idx.search("   ...   ")

    def test_no_match_returns_empty_list(self):
        """Unknown terms yield an empty result, not an error."""
        idx = _make_index()
        self.assertEqual(idx.search("zeppelin"), [])
        # AND semantics: one known + one unknown term also yields nothing.
        self.assertEqual(idx.search("codec zeppelin"), [])

    def test_search_spans_multiple_recordings(self):
        """A query can hit segments across several recordings."""
        idx = _make_index()
        matches = idx.search("budget")
        self.assertEqual(
            sorted({m.recording_id for m in matches}),
            ["retro-friday", "standup-monday"],
        )

    def test_search_on_empty_index_returns_empty(self):
        """Searching before any add() returns no matches."""
        self.assertEqual(TranscriptIndex().search("codec"), [])

    def test_add_accepts_mapping_segments(self):
        """Duck typing: dict-shaped segments index the same as objects."""
        idx = TranscriptIndex()
        added = idx.add(
            "dict-rec", [{"start": 1.0, "end": 2.0, "text": "mapping works"}]
        )
        self.assertEqual(added, 1)
        self.assertEqual(len(idx), 1)
        self.assertEqual(idx.search("mapping")[0].start, 1.0)

    def test_add_rejects_segment_missing_field(self):
        """Segments lacking a required field raise TypeError."""
        idx = TranscriptIndex()
        with self.assertRaises(TypeError):
            idx.add("bad", [{"start": 0.0, "end": 1.0}])


class LoadTranscriptJsonTest(unittest.TestCase):
    """Reading the transcription sidecar JSON shape."""

    def test_roundtrip_from_tmp_file(self):
        """Sidecar JSON loads into Segments and is searchable end to end."""
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
        idx = TranscriptIndex()
        idx.add("recording", segments)
        matches = idx.search("codec roadmap")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].start, 3.2)
        self.assertEqual(matches[0].end, 9.9)

    def test_rejects_non_sidecar_shape(self):
        """A JSON file without a 'segments' list raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(["not", "a", "sidecar"]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_transcript_json(path)

    def test_rejects_segment_missing_key(self):
        """A segment entry missing 'text' raises ValueError naming the key."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.json"
            path.write_text(
                json.dumps({"segments": [{"start": 0.0, "end": 1.0}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as ctx:
                load_transcript_json(path)
        self.assertIn("text", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
