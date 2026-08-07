"""Equivalence tests for transcript and summary token fast paths."""

from __future__ import annotations

import random
import string
import unittest

import summarize
import transcript_search


def reference_content_words(sentence: str) -> list[str]:
    """Return tokens using the pre-fast-path summarizer algorithm."""

    words: list[str] = []
    for raw in sentence.split():
        token = summarize._TOKEN_STRIP_RE.sub("", raw).lower()
        if token and token not in summarize._STOPWORDS:
            words.append(token)
    return words


def reference_search_tokens(text: str) -> list[str]:
    """Return tokens using the pre-fast-path search algorithm."""

    return transcript_search._WORD_RE.findall(text.lower())


class TokenFastPathEquivalenceTests(unittest.TestCase):
    """Optimized tokenization must remain semantically identical."""

    def test_curated_multilingual_and_punctuation_cases(self) -> None:
        """Representative scripts and punctuation preserve exact output."""

        cases = [
            "Topic123",
            "Résumé42",
            "한글123",
            "東京2026",
            "alpha_beta",
            "can't stop",
            "(wrapped) punctuation!",
            "GreekΑ CyrillicА LatinA",
            "１２３ fullwidth",
            "emoji🙂boundary",
            "the and content",
            "",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    summarize._content_words(text),
                    reference_content_words(text),
                )
                self.assertEqual(
                    transcript_search.tokenize(text),
                    reference_search_tokens(text),
                )

    def test_seeded_randomized_equivalence(self) -> None:
        """A deterministic hostile character mix exercises both branches."""

        rng = random.Random(20260807)
        alphabet = (
            string.ascii_letters
            + string.digits
            + " _-'.,!?/\\()[]{}"
            + "éßΑА한글東京１２３🙂"
        )
        for index in range(512):
            text = "".join(
                rng.choice(alphabet) for _ in range(rng.randrange(0, 80))
            )
            with self.subTest(index=index, text=text):
                self.assertEqual(
                    summarize._content_words(text),
                    reference_content_words(text),
                )
                self.assertEqual(
                    transcript_search.tokenize(text),
                    reference_search_tokens(text),
                )


if __name__ == "__main__":
    unittest.main()
