"""Chapter detection from silence structure.

Long recordings (lectures, meetings, podcasts) usually contain natural
sections separated by long stretches of silence.  This module turns a list
of detected silence intervals plus the total media duration into proposed
chapter markers that media players can use for navigation.

The module is deliberately independent of ``media_shrinker``: it accepts any
object exposing ``start_seconds`` and ``end_seconds`` float attributes (the
same duck-type shape as ``media_shrinker.SilenceInterval``), so callers can
feed it silencedetect output without a hard import dependency.

Outputs are exportable as:

* ffmpeg FFMETADATA chapters (``;FFMETADATA1`` format) via
  :func:`to_ffmetadata`, suitable for
  ``ffmpeg -i input -i chapters.txt -map_metadata 1 -codec copy output``.
* A simple JSON listing via :func:`to_json`.

Only the Python standard library is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol


class SilenceLike(Protocol):
    """Duck-type contract for a silence interval.

    Any object with ``start_seconds`` and ``end_seconds`` float attributes
    satisfies this protocol, including ``media_shrinker.SilenceInterval``.
    """

    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class Chapter:
    """A proposed chapter marker covering ``[start, end)`` in seconds."""

    index: int
    start: float
    end: float
    title: str

    @property
    def duration(self) -> float:
        """Return the chapter length in seconds."""

        return self.end - self.start


def _clamped_silences(
    silences: list[SilenceLike] | tuple[SilenceLike, ...],
    total_duration: float,
) -> list[tuple[float, float]]:
    """Sort, clamp, and merge raw silence intervals into clean spans.

    Intervals are clamped to ``[0, total_duration]``, empty or inverted
    spans are discarded, and overlapping or touching spans are merged so
    downstream boundary logic sees each silent region exactly once.
    """

    spans: list[tuple[float, float]] = []
    for silence in silences:
        start = max(0.0, min(float(silence.start_seconds), total_duration))
        end = max(0.0, min(float(silence.end_seconds), total_duration))
        if end > start:
            spans.append((start, end))
    spans.sort()
    merged: list[tuple[float, float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _boundaries_from_silences(
    spans: list[tuple[float, float]],
    total_duration: float,
    min_gap_seconds: float,
) -> list[float]:
    """Return chapter split points at the midpoints of long silences.

    Only silences lasting at least ``min_gap_seconds`` produce a boundary,
    and boundaries falling on the extremes of the timeline are dropped
    because they would create zero-length chapters.
    """

    boundaries: list[float] = []
    for start, end in spans:
        if end - start >= min_gap_seconds:
            midpoint = (start + end) / 2.0
            if 0.0 < midpoint < total_duration:
                boundaries.append(midpoint)
    return boundaries


def _merge_short_chapters(
    edges: list[float],
    min_chapter_seconds: float,
) -> list[float]:
    """Drop boundaries that would create chapters shorter than the minimum.

    ``edges`` is the full edge list ``[0, b1, ..., bn, total_duration]``.
    A too-short chapter is merged into the previous chapter by removing the
    boundary that starts it; a too-short first chapter is merged into the
    following chapter instead, since it has no predecessor.
    """

    kept = list(edges)
    changed = True
    while changed and len(kept) > 2:
        changed = False
        for i in range(1, len(kept)):
            if kept[i] - kept[i - 1] < min_chapter_seconds:
                # Merge into the previous chapter by removing this
                # chapter's starting boundary; the first chapter merges
                # forward by removing its ending boundary instead.
                del kept[i - 1 if i - 1 > 0 else i]
                changed = True
                break
    return kept


def detect_chapters(
    silences: list[SilenceLike] | tuple[SilenceLike, ...],
    total_duration: float,
    min_chapter_seconds: float = 60.0,
    min_gap_seconds: float = 3.0,
) -> list[Chapter]:
    """Propose chapter markers from silence structure.

    Rules:

    * A silence lasting at least ``min_gap_seconds`` ends a chapter at the
      silence midpoint.
    * Chapters shorter than ``min_chapter_seconds`` are merged into the
      previous chapter (the first chapter merges into the next one).
    * The resulting chapters always cover ``[0, total_duration]`` exactly.
    * With no qualifying silences the whole recording is a single chapter.

    Silences are sorted first, so unsorted or overlapping input is handled;
    intervals extending beyond ``total_duration`` (or before zero) are
    clamped.

    Args:
        silences: Objects with ``start_seconds``/``end_seconds`` attributes,
            e.g. ``media_shrinker.SilenceInterval`` instances.
        total_duration: Total media duration in seconds; must be positive.
        min_chapter_seconds: Minimum chapter length before merging applies.
        min_gap_seconds: Minimum silence length that splits chapters.

    Returns:
        Chapters with 1-based ``index`` and titles like ``"Chapter 1"``.

    Raises:
        ValueError: If ``total_duration`` is zero or negative.
    """

    if total_duration <= 0:
        raise ValueError(
            f"total_duration must be positive, got {total_duration!r}"
        )
    spans = _clamped_silences(silences, total_duration)
    boundaries = _boundaries_from_silences(
        spans, total_duration, min_gap_seconds
    )
    edges = [0.0, *boundaries, total_duration]
    edges = _merge_short_chapters(edges, min_chapter_seconds)
    chapters: list[Chapter] = []
    for position in range(len(edges) - 1):
        chapters.append(
            Chapter(
                index=position + 1,
                start=edges[position],
                end=edges[position + 1],
                title=f"Chapter {position + 1}",
            )
        )
    return chapters


def _escape_ffmetadata(value: str) -> str:
    """Escape characters that are special in FFMETADATA values."""

    escaped = value
    for character in ("\\", "=", ";", "#", "\n"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped


def to_ffmetadata(chapters: list[Chapter]) -> str:
    """Serialize chapters to ffmpeg's FFMETADATA1 chapter format.

    The output starts with the ``;FFMETADATA1`` header followed by one
    ``[CHAPTER]`` block per chapter using ``TIMEBASE=1/1000`` with
    ``START``/``END`` expressed in integer milliseconds.  Feed the result to
    ffmpeg via ``-map_metadata`` to embed chapter navigation in the output.
    """

    lines = [";FFMETADATA1"]
    for chapter in chapters:
        lines.append("")
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={round(chapter.start * 1000)}")
        lines.append(f"END={round(chapter.end * 1000)}")
        lines.append(f"title={_escape_ffmetadata(chapter.title)}")
    return "\n".join(lines) + "\n"


def to_json(chapters: list[Chapter]) -> str:
    """Serialize chapters to a simple JSON listing.

    Each chapter becomes an object with ``index``, ``start``, ``end`` (both
    in seconds), and ``title`` keys, preserving chapter order.
    """

    return json.dumps(
        [
            {
                "index": chapter.index,
                "start": chapter.start,
                "end": chapter.end,
                "title": chapter.title,
            }
            for chapter in chapters
        ],
        indent=2,
    )
