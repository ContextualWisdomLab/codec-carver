"""Subtitle and caption export for timestamped transcript segments.

This module converts timestamped transcript segments into standard
subtitle formats: SubRip (``.srt``) and WebVTT (``.vtt``). It is fully
self-contained and depends only on the Python standard library, so it can
be used independently of the transcription pipeline.

The input contract is intentionally small: any object exposing ``start``
and ``end`` (floats, in seconds) and ``text`` (a string) is accepted. A
lightweight :class:`Segment` dataclass is provided for convenience, but
duck-typed objects work equally well.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Union


@dataclass
class Segment:
    """A single timestamped transcript segment.

    Attributes:
        start: Segment start time, in seconds from the beginning of the media.
        end: Segment end time, in seconds from the beginning of the media.
        text: The caption text for this segment. May contain newlines for
            multi-line captions.
    """

    start: float
    end: float
    text: str


def _format_timestamp(seconds: float, separator: str) -> str:
    """Format a time offset as ``HH:MM:SS<sep>mmm``.

    Args:
        seconds: The time offset in seconds. Negative values are clamped to
            zero so that malformed input never produces a negative timestamp.
        separator: The separator placed between seconds and milliseconds.
            Use ``","`` for SubRip and ``"."`` for WebVTT.

    Returns:
        The formatted timestamp string, e.g. ``"01:02:03,004"``.
    """
    if seconds < 0:
        seconds = 0.0
    # Round to whole milliseconds to avoid floating-point drift.
    total_milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def _normalize_text(text: str) -> str:
    """Normalize caption text for cue output.

    Collapses Windows and old-Mac line endings to ``\\n`` and strips a single
    trailing newline so cue blocks are separated cleanly by the caller.

    Args:
        text: The raw caption text.

    Returns:
        The normalized caption text.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip("\n")


def to_srt(segments: Iterable[Segment]) -> str:
    """Render transcript segments as SubRip (``.srt``) text.

    Each cue is numbered sequentially starting at 1 and uses the SubRip
    timestamp format ``HH:MM:SS,mmm``. Cues are separated by a blank line.

    Args:
        segments: An iterable of objects exposing ``start`` and ``end``
            (floats, seconds) and ``text`` (a string).

    Returns:
        The complete SubRip document as a string. An empty iterable yields an
        empty string.
    """
    blocks: List[str] = []
    for index, segment in enumerate(segments, start=1):
        start = _format_timestamp(segment.start, ",")
        end = _format_timestamp(segment.end, ",")
        text = _normalize_text(segment.text)
        blocks.append(f"{index}\n{start} --> {end}\n{text}")
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def to_vtt(segments: Iterable[Segment]) -> str:
    """Render transcript segments as WebVTT (``.vtt``) text.

    The document begins with the mandatory ``WEBVTT`` header. Each cue uses
    the WebVTT timestamp format ``HH:MM:SS.mmm`` and cues are separated by a
    blank line.

    Args:
        segments: An iterable of objects exposing ``start`` and ``end``
            (floats, seconds) and ``text`` (a string).

    Returns:
        The complete WebVTT document as a string. Even with no segments the
        ``WEBVTT`` header is always emitted.
    """
    blocks: List[str] = []
    for segment in segments:
        start = _format_timestamp(segment.start, ".")
        end = _format_timestamp(segment.end, ".")
        text = _normalize_text(segment.text)
        blocks.append(f"{start} --> {end}\n{text}")
    if not blocks:
        return "WEBVTT\n"
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def write_srt(segments: Iterable[Segment], path: Union[str, Path]) -> Path:
    """Write transcript segments to a SubRip (``.srt``) file.

    Args:
        segments: An iterable of objects exposing ``start``, ``end`` and
            ``text``.
        path: Destination file path. Parent directories are not created
            automatically.

    Returns:
        The :class:`~pathlib.Path` that was written.
    """
    destination = Path(path)
    destination.write_text(to_srt(segments), encoding="utf-8")
    return destination


def write_vtt(segments: Iterable[Segment], path: Union[str, Path]) -> Path:
    """Write transcript segments to a WebVTT (``.vtt``) file.

    Args:
        segments: An iterable of objects exposing ``start``, ``end`` and
            ``text``.
        path: Destination file path. Parent directories are not created
            automatically.

    Returns:
        The :class:`~pathlib.Path` that was written.
    """
    destination = Path(path)
    destination.write_text(to_vtt(segments), encoding="utf-8")
    return destination
