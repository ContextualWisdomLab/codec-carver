#!/usr/bin/env python3
"""Optional, configuration-aware speaker diarization for codec-carver.

The module answers "who spoke when?" without making heavy machine-learning
packages mandatory at import time.  The default adapter targets pyannote.audio
4 and the open ``community-1`` pipeline, while injected one-argument backends
remain supported for offline tests and alternative engines.

Two timelines are useful for different consumers:

* regular diarization preserves simultaneous speakers for audit and analysis;
* exclusive diarization assigns one speaker at every instant and is easier to
  align with coarse automatic-speech-recognition timestamps.

Use :mod:`speaker_timeline` after chunked inference when local speaker labels
must be linked across overlapping windows and exported with provenance.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence


DEFAULT_PIPELINE_NAME = "pyannote/speaker-diarization-community-1"
FALLBACK_SPEAKER = "SPEAKER_1"

_INSTALL_HINT = (
    "Speaker diarization requires the optional 'pyannote.audio' package. "
    "Install it with:\n"
    "    pip install pyannote.audio\n"
    "Accept the model terms and provide a Hugging Face token when the selected "
    f"pipeline requires one (default: '{DEFAULT_PIPELINE_NAME}'). Alternatively, "
    "pass a custom backend callable to diarize_file(..., backend=...)."
)


class DiarizationUnavailableError(RuntimeError):
    """Raised when diarization is requested but the selected backend cannot run."""


@dataclass(frozen=True)
class DiarizationConfig:
    """Configuration for the default pyannote speaker-diarization adapter.

    Attributes:
        pipeline_name: Hugging Face or pyannoteAI pipeline identifier.
        hf_token: Explicit model-access token. Environment variables are not
            read implicitly, which keeps credential flow visible to callers.
        num_speakers: Optional exact speaker count.
        min_speakers: Optional lower speaker-count bound.
        max_speakers: Optional upper speaker-count bound.
        exclusive: Prefer exclusive diarization when the backend provides it.
    """

    pipeline_name: str = DEFAULT_PIPELINE_NAME
    hf_token: str | None = None
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    exclusive: bool = True


@dataclass(frozen=True)
class SpeakerTurn:
    """A contiguous interval during which one backend speaker is active.

    Attributes:
        start: Interval start in seconds from the beginning of the audio.
        end: Interval end in seconds from the beginning of the audio.
        speaker: Backend-assigned speaker label.
    """

    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class DiarizationResult:
    """The chronologically ordered result of diarizing one audio file.

    Attributes:
        turns: Speaker turns sorted by start and then end time.
        speaker_count: Number of distinct speaker labels.
    """

    turns: tuple[SpeakerTurn, ...] = field(default_factory=tuple)
    speaker_count: int = 0


@dataclass(frozen=True)
class AttributedSegment:
    """A transcript segment annotated with its maximum-overlap speaker.

    Attributes:
        start: Segment start in seconds.
        end: Segment end in seconds.
        text: Recognized text.
        speaker: Selected speaker or :data:`FALLBACK_SPEAKER`.
    """

    start: float
    end: float
    text: str
    speaker: str


def _validate_config(config: DiarizationConfig) -> None:
    """Validate speaker-count and pipeline invariants before model loading."""
    if not isinstance(config, DiarizationConfig):
        raise ValueError("config must be a DiarizationConfig")
    if not isinstance(config.pipeline_name, str) or not config.pipeline_name.strip():
        raise ValueError("pipeline_name must be a non-empty string")
    for name, value in (
        ("num_speakers", config.num_speakers),
        ("min_speakers", config.min_speakers),
        ("max_speakers", config.max_speakers),
    ):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            raise ValueError(f"{name} must be a positive integer")
    if config.num_speakers is not None and (
        config.min_speakers is not None or config.max_speakers is not None
    ):
        raise ValueError("num_speakers cannot be combined with min_speakers or max_speakers")
    if (
        config.min_speakers is not None
        and config.max_speakers is not None
        and config.min_speakers > config.max_speakers
    ):
        raise ValueError("min_speakers cannot exceed max_speakers")
    if config.hf_token is not None and not isinstance(config.hf_token, str):
        raise ValueError("hf_token must be a string or None")
    if not isinstance(config.exclusive, bool):
        raise ValueError("exclusive must be a boolean")


def _pipeline_kwargs(config: DiarizationConfig) -> dict[str, int]:
    """Return only the speaker-count arguments selected by ``config``."""
    if config.num_speakers is not None:
        return {"num_speakers": config.num_speakers}
    kwargs: dict[str, int] = {}
    if config.min_speakers is not None:
        kwargs["min_speakers"] = config.min_speakers
    if config.max_speakers is not None:
        kwargs["max_speakers"] = config.max_speakers
    return kwargs


def _default_backend(
    audio_path: str,
    config: DiarizationConfig | None = None,
) -> list[SpeakerTurn]:
    """Diarize an audio file with pyannote.audio imported lazily.

    Args:
        audio_path: Local audio path accepted by the pyannote pipeline.
        config: Validated adapter configuration. Defaults to
            :class:`DiarizationConfig`.

    Returns:
        Speaker turns from the regular or exclusive output.

    Raises:
        DiarizationUnavailableError: If importing, loading, decoding, or
            inference fails.
        ValueError: If ``config`` is invalid.
    """
    selected = config if config is not None else DiarizationConfig()
    _validate_config(selected)
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise DiarizationUnavailableError(_INSTALL_HINT) from exc

    try:
        if selected.hf_token is None:
            pipeline = Pipeline.from_pretrained(selected.pipeline_name)
        else:
            pipeline = Pipeline.from_pretrained(selected.pipeline_name, token=selected.hf_token)
    except Exception as exc:  # pragma: no cover - real model access is external
        raise DiarizationUnavailableError(
            f"Could not load the '{selected.pipeline_name}' pipeline: {exc}\n{_INSTALL_HINT}"
        ) from exc

    try:
        output = pipeline(audio_path, **_pipeline_kwargs(selected))
        annotation = _select_annotation(output, exclusive=selected.exclusive)
        return _annotation_to_turns(annotation)
    except Exception as exc:  # pragma: no cover - real codecs/models are external
        raise DiarizationUnavailableError(
            f"Speaker diarization failed for '{audio_path}': {exc}\n{_INSTALL_HINT}"
        ) from exc


def _select_annotation(output: object, *, exclusive: bool) -> object:
    """Select a pyannote 4 result timeline or retain a legacy Annotation."""
    regular = getattr(output, "speaker_diarization", None)
    if regular is None:
        return output
    if exclusive:
        exclusive_output = getattr(output, "exclusive_speaker_diarization", None)
        if exclusive_output is not None:
            return exclusive_output
    return regular


def _annotation_to_turns(annotation: object) -> list[SpeakerTurn]:
    """Convert pyannote 4 iterables and legacy Annotation objects to turns."""
    itertracks = getattr(annotation, "itertracks", None)
    if callable(itertracks):
        return [
            SpeakerTurn(float(segment.start), float(segment.end), str(label))
            for segment, _, label in itertracks(yield_label=True)
        ]

    turns: list[SpeakerTurn] = []
    for row in annotation:  # type: ignore[union-attr]
        if not isinstance(row, tuple) or len(row) not in {2, 3}:
            raise TypeError("unsupported pyannote diarization row")
        if len(row) == 2:
            segment, label = row
        else:
            segment, _, label = row
        turns.append(SpeakerTurn(float(segment.start), float(segment.end), str(label)))
    return turns


def diarize_file(
    audio_path: str,
    *,
    backend: Callable[[str], Iterable[SpeakerTurn]] | None = None,
    config: DiarizationConfig | None = None,
) -> DiarizationResult:
    """Identify who speaks when in ``audio_path``.

    Args:
        audio_path: Path or backend-recognized audio identifier.
        backend: Optional one-argument callable returning speaker turns. This
            compatibility contract intentionally ignores model-specific config.
        config: Configuration for the default backend. It is validated even
            when a custom backend is used so invalid requests fail consistently.

    Returns:
        A sorted :class:`DiarizationResult` with a distinct-speaker count.

    Raises:
        ValueError: If the configuration is invalid.
        DiarizationUnavailableError: If the default backend cannot run.
    """
    selected = config if config is not None else DiarizationConfig()
    _validate_config(selected)
    raw_turns = backend(audio_path) if backend is not None else _default_backend(audio_path, selected)
    turns = tuple(sorted(raw_turns, key=lambda turn: (turn.start, turn.end)))
    return DiarizationResult(turns=turns, speaker_count=len({turn.speaker for turn in turns}))


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Return positive interval overlap in seconds, otherwise ``0.0``."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge_with_transcript(
    turns: Iterable[SpeakerTurn],
    segments: Iterable[object],
) -> list[AttributedSegment]:
    """Assign one speaker to each transcript segment by total time overlap.

    Sorted turn timelines use a prefix-maximum interval index.  This locates
    the first possible overlap with binary search and scans only nearby turns,
    avoiding the quadratic behavior of a full turn-by-segment nested loop.
    Unsorted input retains the legacy scan and its first-seen tie semantics.

    Args:
        turns: Speaker turns, ideally sorted by start time.
        segments: Objects exposing ``start``, ``end``, and ``text`` attributes.

    Returns:
        Attributed segments in the original segment order.
    """
    turn_list = list(turns)
    is_sorted = all(
        turn_list[index].start <= turn_list[index + 1].start
        for index in range(len(turn_list) - 1)
    )
    prefix_max_ends: list[float] = []
    if is_sorted:
        maximum_end = float("-inf")
        for turn in turn_list:
            maximum_end = max(maximum_end, turn.end)
            prefix_max_ends.append(maximum_end)

    merged: list[AttributedSegment] = []
    for segment in segments:
        totals: dict[str, float] = {}
        if is_sorted and turn_list:
            first_candidate = bisect.bisect_right(prefix_max_ends, segment.start)
            for turn in turn_list[first_candidate:]:
                if turn.start >= segment.end:
                    break
                shared = _overlap(segment.start, segment.end, turn.start, turn.end)
                if shared > 0.0:
                    totals[turn.speaker] = totals.get(turn.speaker, 0.0) + shared
        else:
            for turn in turn_list:
                shared = _overlap(segment.start, segment.end, turn.start, turn.end)
                if shared > 0.0:
                    totals[turn.speaker] = totals.get(turn.speaker, 0.0) + shared
        speaker = max(totals, key=totals.__getitem__) if totals else FALLBACK_SPEAKER
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
    """Render attributed segments as one ``[speaker] text`` line each.

    Args:
        merged: Speaker-attributed transcript segments.

    Returns:
        Newline-delimited text, or an empty string for empty input.
    """
    return "\n".join(f"[{item.speaker}] {item.text}" for item in merged)
