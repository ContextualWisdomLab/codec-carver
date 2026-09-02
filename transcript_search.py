"""Fail-closed search boundary for timestamped transcripts.

The legacy implementation tokenized text with a local Unicode-regex rule,
admitted Boolean-AND matches, scored them by summed term frequency, and broke
ties by recording id and timestamp. Those choices materially affected retrieval
membership and ordering without a validated retrieval/evaluation design.

Until such a design is reviewed, non-empty tokenization and search fail closed.
Loading and storing timestamped transcript evidence remains available because it
does not rank, sample, or discard content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "Match",
    "SearchPolicyUnavailable",
    "Segment",
    "TranscriptIndex",
    "load_transcript_json",
    "tokenize",
]


class SearchPolicyUnavailable(RuntimeError):
    """Raised when transcript retrieval lacks a validated selection policy."""


def tokenize(text: str) -> list[str]:
    """Return the empty identity case or fail closed for semantic tokenization."""
    if text == "":
        return []
    raise SearchPolicyUnavailable(
        "transcript tokenization/search is disabled until a validated, "
        "research-backed retrieval and evaluation contract is available"
    )


@dataclass(frozen=True)
class Segment:
    """One timestamped chunk of a transcript."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Match:
    """Compatibility envelope for a future validated retrieval result."""

    recording_id: str
    start: float
    end: float
    text: str
    score: float | None = None


@dataclass(frozen=True)
class _Entry:
    """Internal lossless indexed segment without local relevance features."""

    recording_id: str
    start: float
    end: float
    text: str


def _read_attr(segment: Any, name: str) -> Any:
    """Fetch *name* from a duck-typed segment or mapping."""
    if isinstance(segment, Mapping):
        try:
            return segment[name]
        except KeyError:
            raise TypeError(
                f"segment mapping is missing required key {name!r}"
            ) from None
    try:
        return getattr(segment, name)
    except AttributeError:
        raise TypeError(
            f"segment object is missing required attribute {name!r}"
        ) from None


class TranscriptIndex:
    """Lossless transcript registry with retrieval disabled pending evidence."""

    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, recording_id: str, segments: Iterable[Any]) -> int:
        """Store transcript segments without deriving ranking features."""
        added = 0
        for segment in segments:
            entry = _Entry(
                recording_id=recording_id,
                start=float(_read_attr(segment, "start")),
                end=float(_read_attr(segment, "end")),
                text=str(_read_attr(segment, "text")),
            )
            self._entries.append(entry)
            added += 1
        return added

    def search(self, query: str) -> list[Match]:
        """Fail closed for non-empty retrieval requests without a valid policy."""
        if query == "":
            raise ValueError("query must not be empty")
        raise SearchPolicyUnavailable(
            "transcript search is disabled until a validated, research-backed "
            "retrieval and evaluation contract is available"
        )


def load_transcript_json(path: str | Path) -> list[Segment]:
    """Load timestamped segments losslessly from a transcription sidecar."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("segments"), list):
        raise ValueError(
            f"{path}: expected a JSON object with a 'segments' list"
        )
    segments = []
    for i, item in enumerate(raw["segments"]):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: segments[{i}] is not an object")
        try:
            segments.append(
                Segment(
                    start=float(item["start"]),
                    end=float(item["end"]),
                    text=str(item["text"]),
                )
            )
        except KeyError as exc:
            raise ValueError(
                f"{path}: segments[{i}] is missing key {exc.args[0]!r}"
            ) from None
    return segments
