"""Tests for the fail-closed transcript summarization boundary."""

import unittest
from dataclasses import dataclass

from summarize import SummarizationPolicyUnavailable, Summary, summarize_segments, summarize_text


@dataclass
class FakeSegment:
    """Duck-typed stand-in for a timestamped transcription segment."""

    text: str
    start: float = 0.0
    end: float = 0.0


class TestSummarizeText(unittest.TestCase):
    """Behavioral tests for heuristic-free summarize_text."""

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

    def test_nonempty_text_fails_closed(self):
        with self.assertRaisesRegex(
            SummarizationPolicyUnavailable,
            "validated, research-backed selection and evaluation contract",
        ):
            summarize_text("Codec detection finished. Two streams were recovered.")

    def test_legacy_length_argument_cannot_reenable_selection(self):
        with self.assertRaises(SummarizationPolicyUnavailable):
            summarize_text("Some text.", max_sentences=1)

    def test_multilingual_text_is_not_ranked_by_local_token_rules(self):
        for text in (
            "코덱 복구 작업이 시작되었습니다. 코덱 테이블을 분석했습니다.",
            "映像の解析が完了した。音声の復元も完了した。",
        ):
            with self.assertRaises(SummarizationPolicyUnavailable):
                summarize_text(text)


class TestSummarizeSegments(unittest.TestCase):
    """Behavioral tests for heuristic-free summarize_segments."""

    def test_empty_segment_list_is_lossless_noop(self):
        result = summarize_segments([])
        self.assertEqual(result.summary_text, "")
        self.assertEqual(result.key_sentences, [])
        self.assertEqual(result.word_count, 0)

    def test_nonempty_segments_fail_closed(self):
        segments = [
            FakeSegment(text="Muxer errors detected in the first pass."),
            FakeSegment(text="Muxer retries fixed most muxer errors."),
        ]
        with self.assertRaises(SummarizationPolicyUnavailable):
            summarize_segments(segments)

    def test_length_argument_cannot_enable_segment_ranking(self):
        with self.assertRaises(SummarizationPolicyUnavailable):
            summarize_segments([FakeSegment(text="Hello there.")], max_sentences=1)

    def test_missing_text_attribute_still_surfaces_input_contract_error(self):
        class MissingText:
            pass

        with self.assertRaises(AttributeError):
            summarize_segments([MissingText()])


if __name__ == "__main__":
    unittest.main()
