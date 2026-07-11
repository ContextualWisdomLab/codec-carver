#!/usr/bin/env python3
"""Optional transcription sidecar for Codec Carver outputs.

Codec Carver's core job is turning long recordings into small, archival audio.
This module adds the highest-value follow-on step: producing a searchable text
transcript (and timestamped JSON) alongside each generated audio file.

It is deliberately optional and dependency-free at import time. The default
backend lazily imports ``faster-whisper`` only when a transcription actually
runs; if it is not installed, a clear :class:`TranscriptionUnavailableError`
is raised so callers can skip transcription without failing the conversion.
The backend is injectable, which keeps the whole module unit-testable without
downloading or running any speech model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class TranscriptionUnavailableError(RuntimeError):
    """Raised when no transcription backend is available (e.g. faster-whisper missing)."""


@dataclass(frozen=True)
class TranscriptSegment:
    """A single timestamped span of recognised speech."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    """The full transcript for one audio file."""

    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str | None = None


# A backend takes (audio_path, model_name) and returns a TranscriptResult.
Backend = Callable[[Path, str], TranscriptResult]


def _faster_whisper_backend(audio_path: Path, model_name: str) -> TranscriptResult:
    """Transcribe using faster-whisper, imported lazily so it stays optional."""
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise TranscriptionUnavailableError(
            "faster-whisper is not installed; install it with "
            "`pip install faster-whisper` (or the 'transcribe' extra) to enable "
            "transcription."
        ) from exc

    model = WhisperModel(model_name)
    raw_segments, info = model.transcribe(str(audio_path))
    segments = [
        TranscriptSegment(start=float(s.start), end=float(s.end), text=str(s.text))
        for s in raw_segments
    ]
    full_text = "".join(segment.text for segment in segments).strip()
    language = getattr(info, "language", None)
    return TranscriptResult(text=full_text, segments=segments, language=language)


def transcribe_file(
    audio_path: Path | str,
    *,
    model: str = "base",
    backend: Backend | None = None,
) -> TranscriptResult:
    """Transcribe ``audio_path`` and return a :class:`TranscriptResult`.

    ``backend`` defaults to the lazily-loaded faster-whisper backend but can be
    overridden (used in tests to avoid running a real model).
    """
    chosen = backend or _faster_whisper_backend
    return chosen(Path(audio_path), model)


def write_sidecars(
    result: TranscriptResult, output_audio_path: Path | str
) -> tuple[Path, Path]:
    """Write ``.txt`` and ``.json`` transcript sidecars next to the audio file.

    For ``recording.wav.flac`` this writes ``recording.wav.flac.txt`` and
    ``recording.wav.flac.json``. Returns the two written paths.
    """
    audio_path = Path(output_audio_path)
    txt_path = audio_path.with_name(audio_path.name + ".txt")
    json_path = audio_path.with_name(audio_path.name + ".json")

    txt_path.write_text(result.text.strip() + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "language": result.language,
                "text": result.text.strip(),
                "segments": [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in result.segments
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return txt_path, json_path


def transcribe_output(
    output_audio_path: Path | str,
    *,
    model: str = "base",
    transcribe_fn: Callable[..., TranscriptResult] = transcribe_file,
) -> tuple[Path, Path]:
    """Transcribe a generated audio file and write its sidecars.

    This is the entry point wired into the conversion pipeline. ``transcribe_fn``
    is injectable so the whole path can be unit-tested with a fake transcriber.
    """
    result = transcribe_fn(Path(output_audio_path), model=model)
    return write_sidecars(result, output_audio_path)
