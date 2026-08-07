#!/usr/bin/env python3
"""Immutable data contracts and validation for speaker timeline reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Mapping


class ArtifactIntegrityError(RuntimeError):
    """Raised when an exported artifact cannot pass its integrity checks."""


@dataclass(frozen=True)
class ChunkWindow:
    """A deterministic processing window within a long recording.

    Attributes:
        chunk_id: Stable non-numeric identifier such as ``"chunk_0001"``.
        start: Absolute start time in seconds.
        end: Absolute end time in seconds.
    """

    chunk_id: str
    start: float
    end: float


@dataclass(frozen=True)
class ChunkTranscriptSegment:
    """One transcript segment expressed in chunk-local time.

    Attributes:
        start: Segment start relative to the chunk, in seconds.
        end: Segment end relative to the chunk, in seconds.
        text: Recognized text. Empty text is allowed for explicit events.
        local_speaker: Backend-local speaker label.
        overlapping_speakers: Additional simultaneously active local speakers.
        confidence: Optional calibrated confidence in the closed interval
            ``[0, 1]``.
        is_overlap: Whether the backend explicitly marked overlapped speech.
    """

    start: float
    end: float
    text: str
    local_speaker: str
    overlapping_speakers: tuple[str, ...] = field(default_factory=tuple)
    confidence: float | None = None
    is_overlap: bool = False


@dataclass(frozen=True)
class TranscriptChunk:
    """A transcript window and its absolute offset in the source recording.

    Validation is performed here rather than in
    :class:`ChunkTranscriptSegment` so callers can deserialize untrusted model
    output first and fail at a single chunk boundary.

    Attributes:
        chunk_id: Stable chunk identifier.
        offset: Absolute start of the chunk in seconds.
        segments: Chunk-local transcript segments.
    """

    chunk_id: str
    offset: float
    segments: tuple[ChunkTranscriptSegment, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate the chunk and all segment-level invariants."""
        if not isinstance(self.chunk_id, str) or not self.chunk_id.strip():
            raise ValueError("chunk_id must be a non-empty string")
        _require_finite(self.offset, "offset")
        if self.offset < 0.0:
            raise ValueError("offset must be greater than or equal to zero")
        for index, segment in enumerate(self.segments):
            _validate_segment(segment, index=index)


@dataclass(frozen=True)
class SpeakerLink:
    """Acoustic evidence that two chunk-local labels represent one person.

    Attributes:
        source_chunk_id: Chunk containing the first local speaker.
        source_speaker: First chunk-local speaker label.
        target_chunk_id: Chunk containing the second local speaker.
        target_speaker: Second chunk-local speaker label.
        similarity: Calibrated identity similarity in ``[0, 1]``.
    """

    source_chunk_id: str
    source_speaker: str
    target_chunk_id: str
    target_speaker: str
    similarity: float


@dataclass(frozen=True)
class SegmentSource:
    """Provenance for one model segment contributing to a timeline segment.

    Attributes:
        chunk_id: Originating chunk identifier.
        local_speaker: Originating local speaker label.
        local_start: Start relative to the originating chunk.
        local_end: End relative to the originating chunk.
    """

    chunk_id: str
    local_speaker: str
    local_start: float
    local_end: float


@dataclass(frozen=True)
class TimelineSegment:
    """A globally timed, globally attributed transcript segment.

    Attributes:
        start: Absolute start time in seconds.
        end: Absolute end time in seconds.
        text: Selected user-facing transcription.
        speakers: One or more stable global speaker labels. The first label is
            the primary speaker.
        confidence: Best available confidence among duplicate candidates.
        is_overlap: Whether simultaneous speech is represented.
        sources: Provenance records from every reconciled chunk candidate.
    """

    start: float
    end: float
    text: str
    speakers: tuple[str, ...]
    confidence: float | None
    is_overlap: bool
    sources: tuple[SegmentSource, ...]


@dataclass(frozen=True)
class ReconciliationMetrics:
    """Auditable counts and durations for one reconciliation run.

    Attributes:
        input_segment_count: Number of chunk-local input segments.
        output_segment_count: Number of surviving global segments.
        duplicate_segment_count: Cross-chunk duplicates removed.
        global_speaker_count: Number of stable global speakers.
        rejected_link_count: Contradictory high-confidence links rejected.
        speech_seconds: Union duration covered by any transcript segment.
        overlap_speech_seconds: Union duration marked as simultaneous speech.
    """

    input_segment_count: int
    output_segment_count: int
    duplicate_segment_count: int
    global_speaker_count: int
    rejected_link_count: int
    speech_seconds: float
    overlap_speech_seconds: float


@dataclass(frozen=True)
class ReconciledTimeline:
    """Complete reconciliation result ready for rendering or persistence.

    Attributes:
        segments: Chronologically sorted global transcript segments.
        speaker_map: Mapping from ``"chunk_id:local_speaker"`` to a stable
            global speaker label.
        metrics: Reconciliation quality and volume metrics.
        rejected_links: High-confidence identity links rejected because they
            would merge distinct speakers already present in the same chunk.
    """

    segments: tuple[TimelineSegment, ...]
    speaker_map: Mapping[str, str]
    metrics: ReconciliationMetrics
    rejected_links: tuple[SpeakerLink, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ArtifactBundle:
    """Paths and digest returned after a verified multi-format export.

    Attributes:
        archive_path: Final ZIP archive path.
        manifest_path: Final SHA-256 manifest path.
        archive_sha256: Lowercase SHA-256 digest of the archive bytes.
        files: Final non-archive artifact paths in deterministic order.
    """

    archive_path: Path
    manifest_path: Path
    archive_sha256: str
    files: tuple[Path, ...]


def _require_finite(value: float, name: str) -> None:
    """Raise ``ValueError`` unless ``value`` is a finite real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _require_probability(value: float, name: str) -> None:
    """Raise ``ValueError`` unless ``value`` is a finite probability."""
    _require_finite(value, name)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def _validate_segment(segment: ChunkTranscriptSegment, *, index: int) -> None:
    """Validate one chunk-local transcript segment."""
    if not isinstance(segment, ChunkTranscriptSegment):
        raise ValueError(f"segments[{index}] must be a ChunkTranscriptSegment")
    _require_finite(segment.start, f"segments[{index}].start")
    _require_finite(segment.end, f"segments[{index}].end")
    if segment.start < 0.0:
        raise ValueError(f"segments[{index}].start must be greater than or equal to zero")
    if segment.end <= segment.start:
        raise ValueError(f"segments[{index}].end must be greater than start")
    if not isinstance(segment.text, str):
        raise ValueError(f"segments[{index}].text must be a string")
    if not isinstance(segment.local_speaker, str) or not segment.local_speaker.strip():
        raise ValueError(f"segments[{index}].speaker must be a non-empty string")
    seen = {segment.local_speaker}
    for speaker in segment.overlapping_speakers:
        if not isinstance(speaker, str) or not speaker.strip():
            raise ValueError(f"segments[{index}].overlapping speaker must be non-empty")
        if speaker in seen:
            raise ValueError(f"segments[{index}] contains a duplicate speaker label")
        seen.add(speaker)
    if segment.confidence is not None:
        _require_probability(segment.confidence, f"segments[{index}].confidence")
    if not isinstance(segment.is_overlap, bool):
        raise ValueError(f"segments[{index}].is_overlap must be a boolean")
