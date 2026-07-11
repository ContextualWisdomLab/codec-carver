#!/usr/bin/env python3
"""Optional speaker-diarization hook for codec-carver.

This module answers "who spoke when?" for an audio file and lets callers
attribute transcript segments to speakers. It follows the repository's
optional-AI pattern:

- **Dependency-free at import.** Importing this module never pulls in heavy
  ML libraries; only the standard library is touched.
- **Injectable backend.** ``diarize_file`` accepts any callable that maps an
  audio path to speaker turns, so tests and alternative engines never need
  the real model.
- **Lazy heavy import.** The default backend imports ``pyannote.audio`` only
  when actually invoked.
- **Graceful degradation.** When the optional dependency is missing, a
  :class:`DiarizationUnavailableError` with an actionable install message is
  raised instead of a bare ``ImportError`` at import time.

The pure functions :func:`merge_with_transcript` and :func:`to_text` work
without any model at all, so speaker attribution logic stays fully testable
offline.

Honest note on the optional dependency: the default backend relies on
``pyannote.audio``, a large package that downloads pretrained models on
first use and requires a Hugging Face access token for the gated
``pyannote/speaker-diarization-3.1`` pipeline. Nothing in codec-carver
requires it unless you call :func:`diarize_file` without a custom backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence


DEFAULT_PIPELINE_NAME = "pyannote/speaker-diarization-3.1"

FALLBACK_SPEAKER = "SPEAKER_1"

_INSTALL_HINT = (
    "Speaker diarization requires the optional 'pyannote.audio' package, "
    "which is not installed. Install it with:\n"
    "    pip install pyannote.audio\n"
    "You will also need a Hugging Face access token with permission for "
    f"the gated '{DEFAULT_PIPELINE_NAME}' pipeline "
    "(set HF_TOKEN or pass hf_token). Alternatively, pass your own "
    "backend callable to diarize_file(..., backend=...)."
)


class DiarizationUnavailableError(RuntimeError):
    """Raised when diarization is requested but no backend can run.

    This typically means the optional ``pyannote.audio`` dependency is not
    installed (or its pretrained pipeline could not be loaded). The error
    message always includes actionable installation instructions.
    """


@dataclass(frozen=True)
class SpeakerTurn:
    """A contiguous interval during which a single speaker is talking.

    Attributes:
        start: Interval start in seconds from the beginning of the audio.
        end: Interval end in seconds from the beginning of the audio.
        speaker: Backend-assigned speaker label (e.g. ``"SPEAKER_00"``).
    """

    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class DiarizationResult:
    """The outcome of diarizing one audio file.

    Attributes:
        turns: Chronologically ordered speaker turns.
        speaker_count: Number of distinct speaker labels across all turns.
    """

    turns: tuple[SpeakerTurn, ...] = field(default_factory=tuple)
    speaker_count: int = 0


@dataclass(frozen=True)
class AttributedSegment:
    """A transcript segment annotated with its most likely speaker.

    Attributes:
        start: Segment start in seconds.
        end: Segment end in seconds.
        text: Transcribed text of the segment.
        speaker: Speaker label with the greatest time overlap, or
            :data:`FALLBACK_SPEAKER` when no turn overlaps the segment.
    """

    start: float
    end: float
    text: str
    speaker: str


def _default_backend(audio_path: str) -> list[SpeakerTurn]:
    """Diarize ``audio_path`` with ``pyannote.audio`` (imported lazily).

    The import happens inside this function so that merely importing
    :mod:`diarize` never requires the heavy optional dependency.

    Args:
        audio_path: Path to the audio file to diarize.

    Returns:
        Speaker turns produced by the pretrained pipeline.

    Raises:
        DiarizationUnavailableError: If ``pyannote.audio`` is not installed
            or the pretrained pipeline cannot be loaded.
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise DiarizationUnavailableError(_INSTALL_HINT) from exc

    try:
        pipeline = Pipeline.from_pretrained(DEFAULT_PIPELINE_NAME)
    except Exception as exc:  # pragma: no cover - depends on remote model
        raise DiarizationUnavailableError(
            f"Could not load the '{DEFAULT_PIPELINE_NAME}' pipeline: {exc}\n"
            + _INSTALL_HINT
        ) from exc

    annotation = pipeline(audio_path)
    return [
        SpeakerTurn(start=segment.start, end=segment.end, speaker=str(label))
        for segment, _, label in annotation.itertracks(yield_label=True)
    ]


def diarize_file(
    audio_path: str,
    *,
    backend: Callable[[str], Iterable[SpeakerTurn]] | None = None,
) -> DiarizationResult:
    """Identify who speaks when in ``audio_path``.

    Args:
        audio_path: Path to the audio file to diarize.
        backend: Optional callable mapping an audio path to an iterable of
            :class:`SpeakerTurn`. When omitted, the default backend lazily
            imports ``pyannote.audio``; if that optional dependency is
            missing, :class:`DiarizationUnavailableError` is raised with
            install instructions.

    Returns:
        A :class:`DiarizationResult` whose turns are sorted by start time
        (ties broken by end time) and whose ``speaker_count`` is the number
        of distinct speaker labels.

    Raises:
        DiarizationUnavailableError: If the default backend is selected and
            ``pyannote.audio`` is unavailable.
    """
    runner = backend if backend is not None else _default_backend
    turns = tuple(sorted(runner(audio_path), key=lambda t: (t.start, t.end)))
    speakers = {turn.speaker for turn in turns}
    return DiarizationResult(turns=turns, speaker_count=len(speakers))


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Return the length in seconds of the overlap between two intervals.

    Args:
        a_start: Start of the first interval.
        a_end: End of the first interval.
        b_start: Start of the second interval.
        b_end: End of the second interval.

    Returns:
        The positive overlap duration, or ``0.0`` when the intervals are
        disjoint (or merely touch at a boundary).
    """
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge_with_transcript(
    turns: Iterable[SpeakerTurn],
    segments: Iterable[object],
) -> list[AttributedSegment]:
    """Assign a speaker to each transcript segment by maximum time overlap.

    This is a pure function: no model, file access, or network is involved,
    so it is fully testable offline.

    Args:
        turns: Speaker turns, e.g. from :func:`diarize_file`.
        segments: Duck-typed transcript segments exposing ``.start``,
            ``.end`` (seconds) and ``.text`` attributes — for example the
            segment objects produced by a transcription tool.

    Returns:
        One :class:`AttributedSegment` per input segment, in input order.
        Each segment gets the speaker whose turns overlap it the longest in
        total; when several speakers tie, the one whose overlapping turn
        appears earliest wins. Segments that overlap no turn at all fall
        back to :data:`FALLBACK_SPEAKER`.
    """
    turn_list = list(turns)
    merged: list[AttributedSegment] = []
    for segment in segments:
        totals: dict[str, float] = {}
        for turn in turn_list:
            shared = _overlap(segment.start, segment.end, turn.start, turn.end)
            if shared > 0.0:
                totals[turn.speaker] = totals.get(turn.speaker, 0.0) + shared
        if totals:
            speaker = max(totals, key=lambda name: totals[name])
        else:
            speaker = FALLBACK_SPEAKER
        merged.append(
            AttributedSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=speaker,
            )
        )
    return merged


def to_text(merged: Sequence[AttributedSegment]) -> str:
    """Render speaker-attributed segments as human-readable lines.

    Args:
        merged: Attributed segments, e.g. from :func:`merge_with_transcript`.

    Returns:
        One ``"[speaker] text"`` line per segment, joined by newlines. An
        empty input yields an empty string.
    """
    return "\n".join(f"[{item.speaker}] {item.text}" for item in merged)
