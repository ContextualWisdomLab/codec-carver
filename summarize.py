#!/usr/bin/env python3
"""Extractive transcript summarization with zero external dependencies.

This module turns long transcript text into skimmable notes by selecting the
most representative sentences verbatim from the input. It is an *extractive*
summarizer — it never generates new prose, never paraphrases, and never calls
an LLM or any network service. The algorithm is the classic word-frequency
approach:

1. Split the text into sentences with a regular expression.
2. Build a frequency table of lowercased whitespace tokens, ignoring a small
   English stopword list and bare punctuation.
3. Score each sentence by the average frequency of its content words.
4. Return the top-N sentences, re-ordered to match their original positions.

Limitations (by design, to stay stdlib-only):

* Tokenization is whitespace-based. Languages written without spaces between
  words (Chinese, Japanese) degrade to per-run tokens, so frequency scoring is
  coarse for them; Korean is space-separated and fares better, though particle
  suffixes are not stripped. CJK input is handled without crashing and CJK
  sentence terminators (。！？) are recognized.
* Sentence splitting is heuristic; unusual abbreviations may split early.
"""

import re
from dataclasses import dataclass, field

# Sentence terminators: ASCII . ! ? plus CJK ideographic full stop and
# full-width ! / ?. A sentence ends at one or more terminators followed by
# closing quotes/brackets, then whitespace or end-of-text.
_SENTENCE_END_RE = re.compile(
    r"(?<=[.!?。！？])[\"'”’)\]]*\s+"
)

# Strip leading/trailing punctuation from tokens before frequency counting.
_TOKEN_STRIP_RE = re.compile(r"^\W+|\W+$", re.UNICODE)

# Small English stopword list: enough to keep glue words from dominating the
# frequency table without pulling in any external corpus.
_STOPWORDS = frozenset(
    """
    a an and are as at be but by for from had has have he her his i if in is
    it its me my nor not of on or our she so that the their them then there
    they this to us was we were what when which who will with you your
    """.split()
)


@dataclass
class Summary:
    """Result of an extractive summarization run.

    Attributes:
        summary_text: The selected sentences joined with single spaces, in
            their original document order.
        key_sentences: The selected sentences as a list, in original order.
        word_count: Number of whitespace-separated tokens in the *input*
            text (not the summary).
    """

    summary_text: str
    key_sentences: list = field(default_factory=list)
    word_count: int = 0


def _split_sentences(text):
    """Split ``text`` into sentences using punctuation heuristics.

    Args:
        text: Raw input text.

    Returns:
        A list of non-empty sentence strings with surrounding whitespace
        stripped. Newlines without terminal punctuation do not split
        sentences, so transcripts with hard-wrapped lines stay intact.
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = _SENTENCE_END_RE.split(normalized)
    return [part.strip() for part in parts if part.strip()]


def _content_words(sentence):
    """Extract lowercased content words from a sentence.

    Args:
        sentence: A single sentence string.

    Returns:
        A list of lowercased whitespace tokens with surrounding punctuation
        stripped, excluding stopwords and empty tokens.
    """
    words = []
    for raw in sentence.split():
        if raw.isalnum():
            token = raw.lower()
        else:
            token = _TOKEN_STRIP_RE.sub("", raw).lower()
        if token and token not in _STOPWORDS:
            words.append(token)
    return words


def _score_sentences(sentences):
    """Score sentences by average content-word frequency.

    Args:
        sentences: List of sentence strings.

    Returns:
        A list of float scores parallel to ``sentences``. Sentences with no
        content words score 0.0. Using the *average* (rather than the sum)
        keeps long sentences from winning on length alone.
    """
    frequencies = {}
    tokenized = []
    for sentence in sentences:
        words = _content_words(sentence)
        tokenized.append(words)
        for word in words:
            frequencies[word] = frequencies.get(word, 0) + 1

    scores = []
    for words in tokenized:
        if words:
            scores.append(sum(frequencies[w] for w in words) / len(words))
        else:
            scores.append(0.0)
    return scores


def summarize_text(text, max_sentences=5):
    """Produce an extractive summary of ``text``.

    Selects the ``max_sentences`` highest-scoring sentences (ties broken by
    earlier position) and returns them in their original order, so the
    summary reads chronologically — important for transcripts.

    Args:
        text: The transcript or document text to summarize. May be empty.
        max_sentences: Maximum number of sentences to include in the
            summary. Must be at least 1.

    Returns:
        A :class:`Summary`. For empty or whitespace-only input the summary
        is empty with ``word_count`` 0. If the text has ``max_sentences`` or
        fewer sentences, all of them are returned unchanged (short input is
        effectively passed through).

    Raises:
        ValueError: If ``max_sentences`` is less than 1.
    """
    if max_sentences < 1:
        raise ValueError("max_sentences must be at least 1")

    word_count = len(text.split())
    sentences = _split_sentences(text)
    if not sentences:
        return Summary(summary_text="", key_sentences=[], word_count=0)

    if len(sentences) <= max_sentences:
        selected = list(sentences)
    else:
        scores = _score_sentences(sentences)
        ranked = sorted(
            range(len(sentences)), key=lambda i: (-scores[i], i)
        )
        chosen = sorted(ranked[:max_sentences])
        selected = [sentences[i] for i in chosen]

    return Summary(
        summary_text=" ".join(selected),
        key_sentences=selected,
        word_count=word_count,
    )


def summarize_segments(segments, max_sentences=5):
    """Summarize a sequence of transcript segments.

    Accepts any iterable of duck-typed segment objects exposing a ``.text``
    attribute (e.g. timestamped transcription segments). Segment texts are
    joined with single spaces before summarization, so sentences that span
    segment boundaries are reassembled.

    Args:
        segments: Iterable of objects with a ``.text`` string attribute.
        max_sentences: Maximum number of sentences in the summary. Must be
            at least 1.

    Returns:
        A :class:`Summary` over the joined segment text.

    Raises:
        ValueError: If ``max_sentences`` is less than 1.
        AttributeError: If a segment lacks a ``.text`` attribute.
    """
    joined = " ".join(segment.text for segment in segments)
    return summarize_text(joined, max_sentences=max_sentences)
