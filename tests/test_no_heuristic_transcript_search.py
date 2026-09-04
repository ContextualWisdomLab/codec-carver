"""Regression contract for heuristic-free transcript search selection."""

import unittest

from transcript_search import SearchPolicyUnavailable, Segment, TranscriptIndex, tokenize


class TestNoHeuristicTranscriptSearch(unittest.TestCase):
    """Search cannot rank or tokenize content without a validated retrieval policy."""

    def test_nonempty_search_fails_closed(self):
        index = TranscriptIndex()
        index.add("recording", [Segment(0.0, 1.0, "alpha alpha beta")])
        with self.assertRaises(SearchPolicyUnavailable):
            index.search("alpha")

    def test_nonempty_tokenization_fails_closed(self):
        with self.assertRaises(SearchPolicyUnavailable):
            tokenize("alpha beta")

    def test_empty_tokenization_requires_no_selection(self):
        self.assertEqual(tokenize(""), [])


if __name__ == "__main__":
    unittest.main()
