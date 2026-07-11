"""Tests for the extractive transcript summarizer (summarize.py)."""

import unittest
from dataclasses import dataclass

from summarize import Summary, summarize_segments, summarize_text


@dataclass
class FakeSegment:
    """Duck-typed stand-in for a timestamped transcription segment."""

    text: str
    start: float = 0.0
    end: float = 0.0


class TestSummarizeText(unittest.TestCase):
    """Behavioral tests for summarize_text."""

    def test_empty_input_returns_empty_summary(self):
        result = summarize_text("")
        self.assertIsInstance(result, Summary)
        self.assertEqual(result.summary_text, "")
        self.assertEqual(result.key_sentences, [])
        self.assertEqual(result.word_count, 0)

    def test_whitespace_only_input_returns_empty_summary(self):
        result = summarize_text("   \n\t  ")
        self.assertEqual(result.summary_text, "")
        self.assertEqual(result.key_sentences, [])
        self.assertEqual(result.word_count, 0)

    def test_short_input_returned_as_is(self):
        text = "Codec detection finished. Two streams were recovered."
        result = summarize_text(text, max_sentences=5)
        self.assertEqual(
            result.key_sentences,
            ["Codec detection finished.", "Two streams were recovered."],
        )
        self.assertEqual(
            result.summary_text,
            "Codec detection finished. Two streams were recovered.",
        )
        self.assertEqual(result.word_count, 7)

    def test_single_sentence_without_terminator(self):
        result = summarize_text("no punctuation here at all")
        self.assertEqual(result.key_sentences, ["no punctuation here at all"])
        self.assertEqual(result.word_count, 5)

    def test_max_sentences_respected(self):
        text = " ".join(f"Sentence number {i} talks about topics." for i in range(10))
        result = summarize_text(text, max_sentences=3)
        self.assertEqual(len(result.key_sentences), 3)

    def test_max_sentences_below_one_raises(self):
        with self.assertRaises(ValueError):
            summarize_text("Some text.", max_sentences=0)
        with self.assertRaises(ValueError):
            summarize_text("Some text.", max_sentences=-2)

    def test_top_sentences_selected_by_frequency(self):
        # "codec" appears in three sentences, making it the dominant term.
        # The filler sentences share no repeated content words.
        text = (
            "Codec analysis started today. "
            "Weather stayed calm outside. "
            "Codec recovery needs codec tables. "
            "Lunch arrived late unfortunately. "
            "Broken codec headers hide codec frames."
        )
        result = summarize_text(text, max_sentences=2)
        self.assertEqual(len(result.key_sentences), 2)
        for sentence in result.key_sentences:
            self.assertIn("codec", sentence.lower())
        # The two densest codec sentences must win over the filler ones.
        self.assertNotIn("Weather stayed calm outside.", result.key_sentences)
        self.assertNotIn("Lunch arrived late unfortunately.", result.key_sentences)

    def test_original_order_preserved(self):
        # The highest-scoring sentence appears last in the document; the
        # summary must still present sentences in document order.
        text = (
            "Alpha recovery began early. "
            "Random filler mentions nothing shared. "
            "Alpha frames feed alpha decoding of alpha streams."
        )
        result = summarize_text(text, max_sentences=2)
        self.assertEqual(len(result.key_sentences), 2)
        positions = [text.index(s) for s in result.key_sentences]
        self.assertEqual(positions, sorted(positions))
        # summary_text mirrors key_sentences order.
        self.assertEqual(result.summary_text, " ".join(result.key_sentences))

    def test_stopwords_do_not_dominate_scoring(self):
        # A sentence made almost entirely of stopwords must lose to a
        # sentence carrying the repeated content word.
        text = (
            "It is the and of to a in that. "
            "Transcoding pipeline rebuilt transcoding cache. "
            "Transcoding jobs resumed. "
            "Nothing else happened."
        )
        result = summarize_text(text, max_sentences=1)
        self.assertIn("transcoding", result.key_sentences[0].lower())

    def test_word_count_counts_input_tokens(self):
        text = "One two three. Four five six seven."
        result = summarize_text(text, max_sentences=1)
        self.assertEqual(result.word_count, 7)

    def test_long_input_produces_bounded_summary(self):
        text = " ".join(
            f"Segment {i} discusses container metadata and stream offsets."
            for i in range(500)
        )
        result = summarize_text(text, max_sentences=4)
        self.assertEqual(len(result.key_sentences), 4)
        self.assertLess(len(result.summary_text), len(text))
        self.assertEqual(result.word_count, 500 * 8)

    def test_korean_text_does_not_crash(self):
        text = (
            "코덱 복구 작업이 시작되었습니다. "
            "코덱 테이블을 분석했습니다. "
            "날씨가 좋았습니다. "
            "코덱 헤더를 복원했습니다."
        )
        result = summarize_text(text, max_sentences=2)
        self.assertEqual(len(result.key_sentences), 2)
        for sentence in result.key_sentences:
            self.assertIn(sentence, text)

    def test_cjk_fullwidth_terminators_split_sentences(self):
        text = "映像の解析が完了した。音声の復元も完了した。結果は良好だ。"
        result = summarize_text(text, max_sentences=5)
        # No whitespace after 。 means no split — input passes through whole.
        self.assertEqual(len(result.key_sentences), 1)
        self.assertEqual(result.summary_text, text)

        spaced = "映像の解析が完了した。 音声の復元も完了した。 結果は良好だ。"
        spaced_result = summarize_text(spaced, max_sentences=2)
        self.assertEqual(len(spaced_result.key_sentences), 2)

    def test_ties_broken_by_earlier_position(self):
        # All sentences score identically; the earliest ones must be chosen.
        text = "Alpha beta gamma. Delta epsilon zeta. Eta theta iota. Kappa lambda mu."
        result = summarize_text(text, max_sentences=2)
        self.assertEqual(
            result.key_sentences,
            ["Alpha beta gamma.", "Delta epsilon zeta."],
        )


class TestSummarizeSegments(unittest.TestCase):
    """Behavioral tests for summarize_segments."""

    def test_segments_joined_and_summarized(self):
        segments = [
            FakeSegment(text="Muxer errors detected in the first pass.", start=0.0),
            FakeSegment(text="Muxer retries fixed most muxer errors.", start=4.2),
            FakeSegment(text="Coffee break happened afterwards.", start=9.9),
        ]
        result = summarize_segments(segments, max_sentences=1)
        self.assertEqual(len(result.key_sentences), 1)
        self.assertIn("muxer", result.key_sentences[0].lower())

    def test_sentence_spanning_segment_boundary_is_reassembled(self):
        segments = [
            FakeSegment(text="The bitstream parser found"),
            FakeSegment(text="seventeen recoverable frames."),
        ]
        result = summarize_segments(segments, max_sentences=5)
        self.assertEqual(
            result.key_sentences,
            ["The bitstream parser found seventeen recoverable frames."],
        )

    def test_empty_segment_list(self):
        result = summarize_segments([])
        self.assertEqual(result.summary_text, "")
        self.assertEqual(result.key_sentences, [])
        self.assertEqual(result.word_count, 0)

    def test_max_sentences_validated(self):
        with self.assertRaises(ValueError):
            summarize_segments([FakeSegment(text="Hello there.")], max_sentences=0)

    def test_duck_typing_accepts_any_object_with_text(self):
        class Chunk:
            """Minimal object exposing only .text."""

            def __init__(self, text):
                self.text = text

        result = summarize_segments([Chunk("Only one sentence here.")])
        self.assertEqual(result.key_sentences, ["Only one sentence here."])


if __name__ == "__main__":
    unittest.main()
