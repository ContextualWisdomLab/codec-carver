#!/usr/bin/env python3
"""Public facade for long-form speaker timeline reconciliation.

The implementation is split into narrow modules so the same contracts can be
embedded independently in codec-carver, naruon, or a service boundary without
copying the complete artifact stack. Importing from this facade preserves the
original standalone API.
"""

from speaker_timeline_artifacts import write_artifact_bundle
from speaker_timeline_identity import _SpeakerUnionFind
from speaker_timeline_plan import plan_overlapping_chunks
from speaker_timeline_reconcile import reconcile_chunks
from speaker_timeline_render import (
    render_markdown,
    render_rttm,
    render_srt,
    render_webvtt,
    timeline_to_dict,
)
from speaker_timeline_types import (
    ArtifactBundle,
    ArtifactIntegrityError,
    ChunkTranscriptSegment,
    ChunkWindow,
    ReconciledTimeline,
    ReconciliationMetrics,
    SegmentSource,
    SpeakerLink,
    TimelineSegment,
    TranscriptChunk,
)

__all__ = [
    "ArtifactBundle",
    "ArtifactIntegrityError",
    "ChunkTranscriptSegment",
    "ChunkWindow",
    "ReconciledTimeline",
    "ReconciliationMetrics",
    "SegmentSource",
    "SpeakerLink",
    "TimelineSegment",
    "TranscriptChunk",
    "plan_overlapping_chunks",
    "reconcile_chunks",
    "render_markdown",
    "render_rttm",
    "render_srt",
    "render_webvtt",
    "timeline_to_dict",
    "write_artifact_bundle",
]
