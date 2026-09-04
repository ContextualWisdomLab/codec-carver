#!/usr/bin/env python3
"""Fail-closed transcript summarization boundary.

Codec Carver previously selected source sentences with repository-authored
frequency scoring, a hand-curated stopword list, a fixed output-length default,
and an earlier-position tie-break. Those choices materially changed which
statements survived into a summary without a validated measurement design or an
authoritative summarization standard.

Until a separately reviewed, research-backed selection/evaluation contract is
available, non-empty automatic summarization fails closed. Empty input remains a
lossless no-op and requires no ranking, sampling, threshold, or tie-break.
"""

from dataclasses import dataclass, field


class SummarizationPolicyUnavailable(RuntimeError):
    """Raised when non-empty summarization lacks validated selection evidence."""


@dataclass
class Summary:
    """Result envelope retained for compatibility with lossless empty input."""

    summary_text: str
    key_sentences: list = field(default_factory=list)
    word_count: int = 0


def summarize_text(text, max_sentences=None):
    """Return an empty no-op result or fail closed for non-empty text.

    ``max_sentences`` is retained as a compatibility argument only. It is not a
    decision authority and has no repository-authored default. A future
    implementation may use an explicitly governed output-size requirement only
    after the summarization selector and its evaluation design have independent
    executable provenance.
    """
    if not text.strip():
        return Summary(summary_text="", key_sentences=[], word_count=0)

    raise SummarizationPolicyUnavailable(
        "automatic transcript summarization is disabled until a validated, "
        "research-backed selection and evaluation contract is available"
    )


def summarize_segments(segments, max_sentences=None):
    """Fail closed for non-empty transcript segments without selecting content."""
    joined = " ".join(segment.text for segment in segments)
    return summarize_text(joined, max_sentences=max_sentences)
