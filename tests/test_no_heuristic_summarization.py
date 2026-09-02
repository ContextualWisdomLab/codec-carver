"""Regression contract for heuristic-free transcript summarization."""

import inspect
import unittest
from dataclasses import dataclass

from summarize import SummarizationPolicyUnavailable, summarize_segments, summarize_text


@dataclass
class Segment:
    """Minimal transcript segment fixture."""

    text: str


class TestNoHeuristicSummarization(unittest.TestCase):
    """Automatic summary selection must fail closed without validated evidence."""

    def test_nonempty_text_cannot_be_ranked_without_validated_policy(self):
        with self.assertRaises(SummarizationPolicyUnavailable):
            summarize_text(
                "Alpha beta gamma. Repeated alpha terms used to win. Another sentence."
            )

    def test_nonempty_segments_cannot_be_ranked_without_validated_policy(self):
        with self.assertRaises(SummarizationPolicyUnavailable):
            summarize_segments([Segment("First segment."), Segment("Second segment.")])

    def test_no_repository_authored_summary_length_default(self):
        parameter = inspect.signature(summarize_text).parameters["max_sentences"]
        self.assertIsNone(parameter.default)

    def test_empty_input_remains_lossless_and_requires_no_selection(self):
        result = summarize_text("")
        self.assertEqual(result.summary_text, "")
        self.assertEqual(result.key_sentences, [])
        self.assertEqual(result.word_count, 0)


if __name__ == "__main__":
    unittest.main()
