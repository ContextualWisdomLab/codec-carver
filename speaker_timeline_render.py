#!/usr/bin/env python3
"""Standards-oriented serialization and subtitle rendering for speaker timelines."""

from __future__ import annotations

from dataclasses import asdict
import re

from speaker_timeline_types import ReconciledTimeline


_TIMELINE_SCHEMA_VERSION = "codec-carver/speaker-timeline/v1"
_SAFE_RTTM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def timeline_to_dict(timeline: ReconciledTimeline) -> dict[str, object]:
    """Convert a timeline to an RFC 8259-compatible serializable mapping.

    Args:
        timeline: Reconciled timeline to serialize.

    Returns:
        A deterministic mapping with schema version, metrics, speaker map,
        rejected links, and segment provenance.
    """
    return {
        "schema_version": _TIMELINE_SCHEMA_VERSION,
        "metrics": asdict(timeline.metrics),
        "speaker_map": dict(sorted(timeline.speaker_map.items())),
        "rejected_links": [asdict(link) for link in timeline.rejected_links],
        "segments": [
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "speakers": list(segment.speakers),
                "confidence": segment.confidence,
                "is_overlap": segment.is_overlap,
                "sources": [asdict(source) for source in segment.sources],
            }
            for segment in timeline.segments
        ],
    }


def render_markdown(timeline: ReconciledTimeline, *, title: str = "Speaker-attributed transcript") -> str:
    """Render a human-readable Markdown transcript with audit metrics."""
    lines = [
        f"# {title}", "", "## Reconciliation summary", "",
        f"- Global speakers: {timeline.metrics.global_speaker_count}",
        f"- Input segments: {timeline.metrics.input_segment_count}",
        f"- Output segments: {timeline.metrics.output_segment_count}",
        f"- Boundary duplicates removed: {timeline.metrics.duplicate_segment_count}",
        f"- Rejected contradictory speaker links: {timeline.metrics.rejected_link_count}",
        f"- Speech union: {timeline.metrics.speech_seconds:.3f} seconds",
        f"- Overlapped-speech union: {timeline.metrics.overlap_speech_seconds:.3f} seconds",
        "", "## Transcript", "",
    ]
    for segment in timeline.segments:
        speaker_text = " + ".join(segment.speakers)
        overlap = " · 동시 발화" if segment.is_overlap else ""
        lines.append(f"- [{_format_clock(segment.start)}–{_format_clock(segment.end)}] **{speaker_text}**{overlap}: {segment.text}")
    return "\n".join(lines) + "\n"


def render_srt(timeline: ReconciledTimeline) -> str:
    """Render SubRip captions with stable speaker labels in cue text."""
    cues: list[str] = []
    for index, segment in enumerate(timeline.segments, start=1):
        speakers = " + ".join(segment.speakers)
        cues.append(f"{index}\n{_format_srt_time(segment.start)} --> {_format_srt_time(segment.end)}\n[{speakers}] {segment.text}")
    return "\n\n".join(cues) + ("\n" if cues else "")


def render_webvtt(timeline: ReconciledTimeline) -> str:
    """Render UTF-8 WebVTT cues with voice annotations."""
    cues = ["WEBVTT", ""]
    for segment in timeline.segments:
        speakers = " + ".join(segment.speakers)
        cues.extend([f"{_format_vtt_time(segment.start)} --> {_format_vtt_time(segment.end)}", f"<v {speakers}>{segment.text}", ""])
    return "\n".join(cues)


def render_rttm(timeline: ReconciledTimeline, *, recording_id: str = "recording") -> str:
    """Render Rich Transcription Time Marked speaker turns."""
    if not isinstance(recording_id, str) or not _SAFE_RTTM_ID_RE.fullmatch(recording_id):
        raise ValueError("recording_id must contain only letters, digits, '.', '_', or '-'")
    rows: list[str] = []
    for segment in timeline.segments:
        duration = segment.end - segment.start
        for speaker in segment.speakers:
            rows.append(f"SPEAKER {recording_id} 1 {segment.start:.3f} {duration:.3f} <NA> <NA> {speaker} <NA> <NA>")
    return "\n".join(rows) + ("\n" if rows else "")


def _format_clock(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS.mmm`` for Markdown."""
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _format_srt_time(seconds: float) -> str:
    """Format seconds as a SubRip timestamp."""
    return _format_clock(seconds).replace(".", ",")


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as a WebVTT timestamp."""
    return _format_clock(seconds)
