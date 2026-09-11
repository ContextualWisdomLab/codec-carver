import unittest
from transcript_search import TranscriptIndex

class MockSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text

class TestTranscriptSearchEdgeCases(unittest.TestCase):
    def setUp(self):
        self.idx = TranscriptIndex()
        self.idx.add("rec1", [MockSegment(0.0, 1.0, "hello world testing")])
        self.idx.add("rec1", [MockSegment(1.0, 2.0, "another segment without terms")])

    def test_search_empty_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.idx.search("")

    def test_search_missing_term_returns_empty_list(self):
        self.assertEqual(self.idx.search("missingterm"), [])

    def test_search_multi_term_intersection(self):
        matches = self.idx.search("hello testing")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].text, "hello world testing")

        matches_none = self.idx.search("hello missingterm")
        self.assertEqual(len(matches_none), 0)

if __name__ == "__main__":
    unittest.main()
