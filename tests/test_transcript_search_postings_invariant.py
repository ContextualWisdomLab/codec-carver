"""Regression coverage for transcript search index/postings consistency."""

import unittest

from transcript_search import Segment, TranscriptIndex


class TranscriptSearchPostingsInvariantTest(unittest.TestCase):
    """Broken postings/counts invariants must stay observable to callers."""

    def test_search_does_not_hide_missing_count_for_surviving_candidate(self) -> None:
        """A candidate admitted by postings must still contain every scored term."""
        index = TranscriptIndex()
        index.add("recording", [Segment(0.0, 1.0, "alpha beta")])

        # Corrupt only the count side of the internal invariant: postings still
        # advertise this entry for beta, so scoring must not reinterpret the
        # contradiction as a legitimate zero-frequency term.
        index._entries[0].counts.pop("beta")

        with self.assertRaises(KeyError):
            index.search("alpha beta")


if __name__ == "__main__":
    unittest.main()
