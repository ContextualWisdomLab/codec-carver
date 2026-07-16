#!/usr/bin/env python3
"""Python API for GPU transcription and Rust-backed audio library curation.

The API keeps model orchestration in Python, where Apple MLX and CUDA Whisper
implementations are mature, while delegating byte-heavy hashing and filesystem
mutations to ``codec-carver-core``. It never invokes Ollama and refuses a CPU
fallback when GPU transcription is requested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import time
import wave
import weakref
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-turbo-q4"
DEFAULT_CUDA_MODEL = "large-v3-turbo"
DEFAULT_PREFETCH_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_STAGE_STALL_TIMEOUT_SECONDS = 420
STAGE_TOTAL_TIMEOUT_MULTIPLIER = 4
MACOS_SF_DATALESS = 0x40000000
MIN_TRANSCRIBABLE_SECONDS = 0.5
SHA256_RE = re.compile(r"[0-9a-f]{64}")
STANDARD_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:__[^/]+)*__sha256-[0-9a-f]{12}$"
)
STANDARD_SHA_RE = re.compile(r"__sha256-(?P<prefix>[0-9a-f]{12})(?:\.|$)")
STAGE_SOURCE_NOT_READY_RE = re.compile(
    r"STAGE_SOURCE_NOT_READY copied (?P<copied>\d+) of (?P<expected>\d+) bytes"
)
FILLER_RE = re.compile(r"\b(?:어|음|아|그|저기|그러니까|뭐지)\b[,.!?\s]*")
SPACE_RE = re.compile(r"\s+")
UNSAFE_NAME_RE = re.compile(r"[^0-9A-Za-z가-힣._-]+")
STOCK_HALLUCINATION_RE = re.compile(
    r"(?:다음-(?:영상|비디오)에서-만나요|이-시각-세계였습니다|"
    r"시청해-주셔서-감사합니다|이곳은-이곳에서|다음-주에-만나요)"
)
DESCRIPTION_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
DESCRIPTION_PARTICLE_SUFFIXES = (
    "으로부터",
    "에서부터",
    "에게서",
    "이라고",
    "이라는",
    "으로써",
    "으로서",
    "까지",
    "부터",
    "에게",
    "한테",
    "께서",
    "에서",
    "으로",
    "라고",
    "에는",
    "이나",
    "이나마",
    "처럼",
    "보다",
    "하고",
    "하고는",
    "과는",
    "와는",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "의",
    "도",
    "와",
    "과",
    "로",
    "만",
)
DESCRIPTION_STOPWORDS = frozenset(
    {
        "about",
        "and",
        "that",
        "the",
        "this",
        "거",
        "거기",
        "거는",
        "거를",
        "거지",
        "것",
        "것도",
        "것들",
        "것은",
        "것을",
        "게",
        "걸",
        "그",
        "그게",
        "그거",
        "그걸",
        "그냥",
        "그런",
        "그렇게",
        "그런데",
        "그리고",
        "그래서",
        "그러니까",
        "그러면",
        "근데",
        "나는",
        "나중",
        "너무",
        "다시",
        "다음",
        "대해서",
        "대한",
        "되는",
        "돼",
        "뭔가",
        "뭐",
        "뭘",
        "많이",
        "맞습니다",
        "먼저",
        "바로",
        "보고",
        "부분",
        "보면",
        "보시면",
        "사실",
        "수",
        "수는",
        "아니고",
        "아까",
        "아주",
        "안",
        "앞으로",
        "어떤",
        "어떻게",
        "여기",
        "여기서",
        "왜",
        "우리",
        "우리가",
        "위해서",
        "이",
        "이거",
        "이거는",
        "이게",
        "이런",
        "이렇게",
        "이제",
        "있고",
        "있는",
        "있다",
        "있도록",
        "있습니다",
        "있으면",
        "있어요",
        "일단",
        "일단은",
        "저",
        "제가",
        "저는",
        "저희",
        "저희가",
        "제대로",
        "좀",
        "지금",
        "진짜",
        "하게",
        "하고",
        "하는",
        "하는지",
        "하지만",
        "한번",
        "해서",
    }
)
DESCRIPTION_DISPLAY_STOPWORDS = frozenset({"결론적", "관해서", "내가", "되게"})


class GpuTranscriptionUnavailableError(RuntimeError):
    """Raised when no supported GPU transcription runtime is available."""


@dataclass(frozen=True)
class TranscriptionConfig:
    """GPU transcription settings shared across a whole library run."""

    accelerator: str = "auto"
    model: str | None = None
    language: str | None = "ko"
    word_timestamps: bool = False


class RustBackend:
    """One-process-per-batch bridge to the optimized Rust backend."""

    def __init__(self, binary: Path | str | None = None) -> None:
        """Resolve an explicit, locally built, or PATH-installed backend."""

        candidates = []
        if binary is not None:
            candidates.append(Path(binary).expanduser().resolve())
        candidates.extend(
            [
                Path(__file__).parent
                / "rust-core"
                / "target"
                / "release"
                / "codec-carver-core",
                Path(__file__).parent
                / "rust-core"
                / "target"
                / "debug"
                / "codec-carver-core",
            ]
        )
        self.binary = next(
            (candidate.resolve() for candidate in candidates if candidate.is_file()),
            None,
        )
        if self.binary is None:
            raise FileNotFoundError(
                "codec-carver-core not found; run "
                "`cargo build --release --manifest-path rust-core/Cargo.toml`"
            )

    def inventory(
        self, root: Path, output: Path, *, threads: int | None = None
    ) -> dict[str, Any]:
        """Create a SHA-256/TMK inventory in one Rust backend invocation."""

        command = [
            str(self.binary),
            "inventory",
            "--root",
            str(root),
            "--output",
            str(output),
        ]
        if threads is not None:
            command.extend(["--threads", str(threads)])
        return self._run_json(command)

    def inspect(
        self, root: Path, relative_path: str, *, timeout_seconds: float = 14_400
    ) -> dict[str, Any]:
        """Hash and inspect one already-materialized relative path."""

        return self._run_json(
            [
                str(self.binary),
                "inspect",
                "--root",
                str(root),
                "--path",
                relative_path,
            ],
            timeout_seconds=timeout_seconds,
        )

    def stage(
        self,
        root: Path,
        relative_path: str,
        staging_dir: Path,
        *,
        timeout_seconds: float = 14_400,
        total_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Stream one placeholder with separate stall and absolute time bounds."""

        if timeout_seconds <= 0:
            raise ValueError("stage stall timeout must be positive")
        if total_timeout_seconds is None:
            total_timeout_seconds = timeout_seconds * STAGE_TOTAL_TIMEOUT_MULTIPLIER
        if total_timeout_seconds <= 0:
            raise ValueError("stage total timeout must be positive")
        command = [
            str(self.binary),
            "stage",
            "--root",
            str(root),
            "--path",
            relative_path,
            "--staging-dir",
            str(staging_dir),
        ]
        started = time.monotonic()
        deadline = started + total_timeout_seconds
        last_progress = started
        max_incomplete_bytes = 0
        while True:
            now = time.monotonic()
            total_remaining = deadline - now
            if total_remaining <= 0:
                raise subprocess.TimeoutExpired(command, total_timeout_seconds)
            stall_remaining = timeout_seconds - (now - last_progress)
            remaining = max(0.01, min(total_remaining, stall_remaining))
            try:
                return self._run_stage_json(
                    command,
                    staging_dir,
                    stall_timeout_seconds=remaining,
                )
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr or ""
                incomplete = STAGE_SOURCE_NOT_READY_RE.search(stderr)
                if incomplete is None:
                    raise
                copied = int(incomplete.group("copied"))
                now = time.monotonic()
                if copied > max_incomplete_bytes:
                    max_incomplete_bytes = copied
                    last_progress = now
                total_remaining = deadline - now
                stall_remaining = timeout_seconds - (now - last_progress)
                if total_remaining <= 0 or stall_remaining <= 0:
                    raise subprocess.TimeoutExpired(
                        command,
                        total_timeout_seconds
                        if total_remaining <= 0
                        else timeout_seconds,
                        output=exc.output,
                        stderr=stderr,
                    ) from exc
                time.sleep(min(1.0, total_remaining, stall_remaining))

    def evict(
        self, root: Path, relative_path: str, *, timeout_seconds: float = 30
    ) -> dict[str, Any]:
        """Release one iCloud file's local blocks through native macOS FileManager."""

        if timeout_seconds <= 0:
            raise ValueError("eviction timeout must be positive")
        return self._run_json(
            [
                str(self.binary),
                "evict",
                "--root",
                str(root),
                "--path",
                relative_path,
            ],
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _run_stage_json(
        command: list[str],
        staging_dir: Path,
        *,
        stall_timeout_seconds: float,
    ) -> dict[str, Any]:
        """Decode a stage response while resetting its timeout on byte progress."""

        if stall_timeout_seconds <= 0:
            raise ValueError("stage stall timeout must be positive")
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        pattern = f".codec-carver-{process.pid}-*.partial"
        observed_sizes: tuple[tuple[str, int], ...] = ()
        last_activity = time.monotonic()
        try:
            while True:
                remaining = max(
                    0.01,
                    min(
                        1.0,
                        stall_timeout_seconds - (time.monotonic() - last_activity),
                    ),
                )
                try:
                    stdout, stderr = process.communicate(timeout=remaining)
                except subprocess.TimeoutExpired as exc:
                    now = time.monotonic()
                    current_sizes = tuple(
                        sorted(
                            (partial.name, partial.stat().st_size)
                            for partial in staging_dir.glob(pattern)
                        )
                    )
                    if current_sizes != observed_sizes:
                        observed_sizes = current_sizes
                        last_activity = now
                    if now - last_activity < stall_timeout_seconds:
                        continue
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(
                        command,
                        stall_timeout_seconds,
                        output=stdout,
                        stderr=stderr,
                    ) from exc
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(
                        process.returncode,
                        command,
                        output=stdout,
                        stderr=stderr,
                    )
                return json.loads(stdout)
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.communicate()
            raise
        finally:
            for partial in staging_dir.glob(pattern):
                remove_staged_file(staging_dir, partial)

    def apply(self, plan: Path, journal: Path, *, execute: bool) -> dict[str, Any]:
        """Validate or execute an auditable mutation plan in Rust."""

        command = [
            str(self.binary),
            "apply",
            "--plan",
            str(plan),
            "--journal",
            str(journal),
        ]
        if execute:
            command.append("--execute")
        return self._run_json(command)

    @staticmethod
    def _run_json(
        command: list[str], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        """Run a backend command without a shell and decode its JSON response."""

        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout_seconds,
        )
        return json.loads(completed.stdout)


class GpuTranscriber:
    """Persistent-model Whisper adapter for Metal/MLX and NVIDIA CUDA."""

    def __init__(self, config: TranscriptionConfig = TranscriptionConfig()) -> None:
        """Select a real GPU backend; no CPU or Ollama fallback is permitted."""

        accelerator = config.accelerator.lower()
        if accelerator == "auto":
            accelerator = (
                "mlx"
                if platform.system() == "Darwin" and platform.machine() == "arm64"
                else "cuda"
            )
        if accelerator not in {"mlx", "cuda"}:
            raise ValueError("accelerator must be one of: auto, mlx, cuda")
        self.config = config
        self.accelerator = accelerator
        self.model = config.model or (
            DEFAULT_MLX_MODEL if accelerator == "mlx" else DEFAULT_CUDA_MODEL
        )
        self._cuda_model: Any | None = None
        self._initialize_runtime()

    def _initialize_runtime(self) -> None:
        """Import and initialize only the selected GPU runtime."""

        if self.accelerator == "mlx":
            try:
                import mlx.core as mx  # type: ignore[import-not-found]
                import mlx_whisper  # type: ignore[import-not-found]  # noqa: F401
            except ImportError as exc:
                raise GpuTranscriptionUnavailableError(
                    "MLX GPU transcription is unavailable; install the `transcribe-mlx` extra"
                ) from exc
            mx.set_default_device(mx.gpu)
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        except ImportError as exc:
            raise GpuTranscriptionUnavailableError(
                "CUDA transcription is unavailable; install the `transcribe-cuda` extra"
            ) from exc
        try:
            self._cuda_model = WhisperModel(
                self.model, device="cuda", compute_type="float16"
            )
        except Exception as exc:
            raise GpuTranscriptionUnavailableError(
                "faster-whisper could not initialize an NVIDIA CUDA GPU"
            ) from exc

    def transcribe(self, audio_path: Path) -> dict[str, Any]:
        """Transcribe one recording while retaining timestamps and language metadata."""

        started = time.perf_counter()
        duration_seconds = audio_duration_seconds(audio_path)
        if (
            duration_seconds is not None
            and duration_seconds < MIN_TRANSCRIBABLE_SECONDS
        ):
            return {
                "text": "",
                "segments": [],
                "language": self.config.language,
                "accelerator": self.accelerator,
                "model": self.model,
                "duration_seconds": round(duration_seconds, 6),
                "quality_flags": ["too_short_for_reliable_speech"],
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        if self.accelerator == "mlx":
            import mlx_whisper  # type: ignore[import-not-found]

            raw = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=self.model,
                language=self.config.language,
                word_timestamps=self.config.word_timestamps,
                condition_on_previous_text=False,
                temperature=0.0,
                hallucination_silence_threshold=(
                    2.0 if self.config.word_timestamps else None
                ),
                verbose=None,
            )
            segments = [
                normalize_segment(segment) for segment in raw.get("segments", [])
            ]
            text = trusted_transcript_text(segments, fallback=str(raw.get("text", "")))
            language = raw.get("language")
        else:
            raw_segments, info = self._cuda_model.transcribe(
                str(audio_path),
                language=self.config.language,
                word_timestamps=self.config.word_timestamps,
                vad_filter=True,
                condition_on_previous_text=False,
                beam_size=1,
                best_of=1,
            )
            segments = []
            for segment in raw_segments:
                normalized = {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": str(segment.text).strip(),
                }
                words = getattr(segment, "words", None)
                if words:
                    normalized["words"] = [
                        {"probability": float(word.probability)} for word in words
                    ]
                segments.append(normalize_segment(normalized))
            text = trusted_transcript_text(segments)
            language = getattr(info, "language", None)
        return {
            "text": text,
            "segments": segments,
            "language": language,
            "accelerator": self.accelerator,
            "model": self.model,
            "duration_seconds": duration_seconds,
            "quality_flags": [],
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


def trusted_ffprobe_binary() -> Path | None:
    """Resolve ffprobe only from an explicit absolute path or fixed system roots."""

    configured = os.environ.get("CODEC_CARVER_FFPROBE")
    candidates = []
    if configured:
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            raise ValueError("CODEC_CARVER_FFPROBE must be an absolute path")
        candidates.append(configured_path)
    candidates.extend(
        Path(value)
        for value in (
            "/opt/homebrew/bin/ffprobe",
            "/usr/local/bin/ffprobe",
            "/usr/bin/ffprobe",
        )
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )


def audio_duration_seconds(audio_path: Path) -> float | None:
    """Probe duration cheaply from WAV headers, then fall back to ffprobe."""

    if not audio_path.is_file():
        return None
    if audio_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(audio_path), "rb") as source:
                return source.getnframes() / source.getframerate()
        except (EOFError, wave.Error, ZeroDivisionError):
            pass
    ffprobe = trusted_ffprobe_binary()
    if not ffprobe:
        return None
    try:
        completed = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            timeout=60,
        )
        return float(completed.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def normalize_segment(segment: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Whisper segment to the stable sidecar and confidence schema."""

    normalized = {
        "start": float(segment.get("start", 0.0)),
        "end": float(segment.get("end", 0.0)),
        "text": str(segment.get("text", "")).strip(),
    }
    probabilities = [
        float(word["probability"])
        for word in segment.get("words", [])
        if word.get("probability") is not None
    ]
    if probabilities:
        word_probability = sum(probabilities) / len(probabilities)
        normalized["word_probability"] = round(word_probability, 6)
        normalized["low_confidence"] = (
            normalized["end"] - normalized["start"] < 0.5 and word_probability < 0.25
        )
    return normalized


def trusted_transcript_text(
    segments: list[dict[str, Any]], *, fallback: str = ""
) -> str:
    """Exclude only ultra-short, low-confidence hallucinations from usable text."""

    trusted = [
        str(segment.get("text", "")).strip()
        for segment in segments
        if not segment.get("low_confidence") and str(segment.get("text", "")).strip()
    ]
    if trusted:
        return " ".join(trusted)
    return "" if segments else fallback.strip()


def description_terms(value: str) -> list[tuple[str, str]]:
    """Return display tokens and particle-normalized keys for topic scoring."""

    terms = []
    for display in DESCRIPTION_TOKEN_RE.findall(value):
        key = display.casefold()
        if key.isdecimal() or len(key) < 2 or len(set(key)) == 1:
            continue
        while True:
            stripped = False
            for suffix in DESCRIPTION_PARTICLE_SUFFIXES:
                if key.endswith(suffix) and len(key) - len(suffix) >= 2:
                    key = key[: -len(suffix)]
                    stripped = True
                    break
            if not stripped:
                break
        if len(key) < 2 or key in DESCRIPTION_STOPWORDS:
            continue
        terms.append((display[: len(key)], key))
    return terms


def topical_transcript_description(values: list[str], *, limit: int) -> str | None:
    """Select a compact, corpus-central phrase from a long transcript."""

    occurrence_count = Counter(values)
    term_frequency = Counter(
        key
        for value in values
        for key in {key for _display, key in description_terms(value)}
    )

    def is_topical(key: str) -> bool:
        """Keep terms repeated across the transcript without being ubiquitous."""

        frequency = term_frequency[key]
        return frequency >= 2 and frequency * 2 <= len(values)

    ranked: list[tuple[tuple[float, int, int, int], list[tuple[str, str]]]] = []
    for index, value in enumerate(values):
        if occurrence_count[value] != 1:
            continue
        terms = description_terms(value)
        unique_terms = []
        seen = set()
        for display, key in terms:
            if key not in seen:
                seen.add(key)
                unique_terms.append((display, key))
        topical = [term for term in unique_terms if is_topical(term[1])]
        if len(topical) < 2:
            continue
        topic_score = sum(min(term_frequency[key], 24) for _display, key in topical)
        score = (
            topic_score / (len(topical) ** 0.5),
            topic_score,
            -abs(len(topical) - 4),
            -index,
        )
        ranked.append((score, unique_terms))
    if not ranked:
        return None
    _score, terms = max(ranked, key=lambda item: item[0])
    selected = [term for term in terms if is_topical(term[1])]
    if len(selected) < 3:
        selected_keys = {key for _display, key in selected}
        selected.extend(term for term in terms if term[1] not in selected_keys)
    displayed = [
        (display, key)
        for display, key in selected
        if key not in DESCRIPTION_DISPLAY_STOPWORDS
    ]
    source = " ".join(display for display, _key in displayed[:6])
    return sanitize_component(source, limit=limit) if source else None


def transcript_description(transcript: dict[str, Any], *, limit: int = 48) -> str:
    """Derive a deterministic, transcript-central filename description."""

    segment_values = [
        str(segment.get("text", "")).strip()
        for segment in transcript.get("segments", [])
        if str(segment.get("text", "")).strip()
    ]
    stock_segment_count = sum(
        bool(STOCK_HALLUCINATION_RE.search(sanitize_component(value, limit=256)))
        for value in segment_values
    )
    if segment_values and stock_segment_count * 4 >= len(segment_values):
        return "무음-또는-전사불명"
    candidates = [
        str(segment.get("text", "")).strip()
        for segment in transcript.get("segments", [])[:12]
        if not segment.get("low_confidence") and str(segment.get("text", "")).strip()
    ]
    if not candidates:
        candidates = [str(transcript.get("text", "")).strip()]
    cleaned = [
        SPACE_RE.sub(" ", FILLER_RE.sub("", value)).strip(" .,!?")
        for value in candidates
    ]
    duration = transcript.get("duration_seconds")
    full_text = SPACE_RE.sub(
        " ", FILLER_RE.sub("", str(transcript.get("text", "")))
    ).strip(" .,!?")
    if (
        duration is not None
        and float(duration) < 30
        and (
            full_text
            in {"다음 영상에서 만나요", "다음 비디오에서 만나요", "감사합니다"}
        )
    ):
        return "무음-또는-전사불명"
    all_cleaned = [
        SPACE_RE.sub(" ", FILLER_RE.sub("", value)).strip(" .,!?")
        for value in segment_values
        if not STOCK_HALLUCINATION_RE.search(sanitize_component(value, limit=256))
    ]
    if len(all_cleaned) > 12:
        topical = topical_transcript_description(all_cleaned, limit=limit)
        if topical:
            return topical
    meaningful = [
        value
        for value in cleaned
        if len(value) >= 4
        and not STOCK_HALLUCINATION_RE.search(sanitize_component(value, limit=limit))
        and cleaned.count(value) == 1
    ]
    source = max(
        meaningful[:5],
        key=lambda value: (len(set(value.split())), len(value)),
        default="무음-또는-전사불명",
    )
    return sanitize_component(source, limit=limit)


def sanitize_component(value: str, *, limit: int) -> str:
    """Convert arbitrary transcript/address text into a portable filename component."""

    normalized = SPACE_RE.sub("-", value.strip())
    normalized = UNSAFE_NAME_RE.sub("-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized[:limit].rstrip("-._") or "미상"


def standard_filename(
    record: dict[str, Any], transcript: dict[str, Any], recorded_at: str
) -> str:
    """Build the date/location/transcript/SHA-256 standard filename."""

    timestamp = datetime.fromisoformat(recorded_at).strftime("%Y-%m-%d_%H-%M-%S")
    components = [timestamp]
    if record.get("location"):
        components.append(sanitize_component(str(record["location"]), limit=32))
    components.append(transcript_description(transcript))
    components.append(f"sha256-{record['sha256'][:12]}")
    stem = "__".join(components)
    if not STANDARD_NAME_RE.match(stem):
        raise ValueError(f"generated filename does not satisfy standard: {stem}")
    return f"{stem}.{str(record['extension']).lower()}"


def is_existing_standard_filename(record: dict[str, Any], recorded_at: str) -> bool:
    """Recognize a valid SHA-bound standard name without recomputing its description."""

    path = Path(record["path"])
    if not STANDARD_NAME_RE.fullmatch(path.stem):
        return False
    if path.suffix.casefold() != f".{str(record['extension']).casefold()}":
        return False
    components = path.stem.split("__")
    timestamp = datetime.fromisoformat(recorded_at).strftime("%Y-%m-%d_%H-%M-%S")
    if len(components) < 3 or components[0] != timestamp:
        return False
    if components[-1] != f"sha256-{record['sha256'][:12]}":
        return False
    if record.get("location"):
        location = sanitize_component(str(record["location"]), limit=32)
        if len(components) < 4 or components[1] != location:
            return False
    return True


def validate_sha256(value: Any, *, label: str = "SHA-256") -> str:
    """Require one canonical lowercase full SHA-256 digest."""

    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def validate_relative_path(root: Path, value: Any, *, label: str) -> str:
    """Normalize an inventory path and reject every root-escape representation."""

    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty relative path")
    if "\\" in value or re.match(r"^[A-Za-z]:", value) or value.startswith("//"):
        raise ValueError(f"{label} contains a non-portable absolute path: {value!r}")
    relative = Path(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError(f"{label} must stay beneath the library root: {value!r}")
    root = root.resolve()
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"{label} contains a symlink: {value!r}")
    resolved = (root / relative).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} escapes the library root: {value!r}")
    return relative.as_posix()


def ensure_private_directory(path: Path) -> None:
    """Create an owner-only directory and refuse a direct symlink."""

    if path.is_symlink():
        raise ValueError(f"private directory must not be a symlink: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"private directory is not a real directory: {path}")
    path.chmod(0o700)


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    """Persist owner-only JSON through a same-directory atomic replacement."""

    ensure_private_directory(path.parent)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def atomic_text_write(path: Path, value: str) -> None:
    """Persist sensitive transcript text with owner-only permissions."""

    ensure_private_directory(path.parent)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def safe_transcript_path(
    transcript_dir: Path, sha256: Any, suffix: str = ".json"
) -> Path:
    """Build one SHA-keyed transcript path without accepting path syntax."""

    validate_sha256(sha256, label="transcript SHA-256")
    if suffix not in {".json", ".txt"}:
        raise ValueError(f"unsupported transcript suffix: {suffix}")
    ensure_private_directory(transcript_dir)
    return transcript_dir / f"{sha256}{suffix}"


class AudioLibrary:
    """Public Python API for the end-to-end curation workflow."""

    def __init__(self, root: Path | str, backend: RustBackend | None = None) -> None:
        """Bind the API to one library root and one Rust backend."""

        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(
                f"audio library root is not a directory: {self.root}"
            )
        self.state_dir = self.root / ".codec-carver"
        self._ensure_secure_state_dir()
        root_key = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16]
        temporary_root = Path(tempfile.gettempdir())
        if temporary_root.is_symlink():
            raise ValueError(f"temporary root must not be a symlink: {temporary_root}")
        temporary_root = temporary_root.resolve()
        self.staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f"codec-carver-{root_key}-",
                dir=temporary_root,
            )
        )
        self.staging_dir.chmod(0o700)
        self._staging_finalizer = weakref.finalize(
            self,
            shutil.rmtree,
            self.staging_dir,
            ignore_errors=True,
        )
        self.backend = backend or RustBackend()

    def inventory(self, *, threads: int | None = None) -> dict[str, Any]:
        """Generate the canonical SHA-256/TMK inventory."""

        inventory_path = self.state_dir / "inventory.json"
        previous_manifest = None
        if inventory_path.is_file():
            previous_bytes = inventory_path.read_bytes()
            previous_manifest = json.loads(previous_bytes)
            history_path = (
                self.state_dir
                / "inventory-history"
                / f"{hashlib.sha256(previous_bytes).hexdigest()}.json"
            )
            if not history_path.is_file():
                atomic_json_write(history_path, previous_manifest)
        manifest = self.backend.inventory(
            self.root,
            inventory_path,
            threads=threads,
        )
        if "files" in manifest:
            restore_inventory_evidence(
                manifest,
                self.state_dir,
                previous_manifest=previous_manifest,
            )
            atomic_json_write(inventory_path, manifest)
        return manifest

    def transcribe(
        self,
        config: TranscriptionConfig = TranscriptionConfig(),
        *,
        max_files: int | None = None,
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Transcribe each unique SHA-256 once with a persistent GPU model."""

        manifest = self._load_inventory()
        records = unique_audio_records(manifest)
        if max_files is not None:
            records = records[:max_files]
        transcriber = GpuTranscriber(config)
        transcript_dir = self.state_dir / "transcripts"
        completed = skipped = failed = 0
        failures = []
        for index, record in enumerate(records, start=1):
            status = "failed"
            try:
                self._verify_materialized_record(record)
                sha256 = validate_sha256(record["sha256"])
                output = safe_transcript_path(transcript_dir, sha256)
                text_output = safe_transcript_path(transcript_dir, sha256, ".txt")
                if output.is_file():
                    skipped += 1
                    status = "cached"
                else:
                    result = transcriber.transcribe(self.root / record["path"])
                    result.update(
                        {
                            "schema_version": 1,
                            "sha256": sha256,
                            "source_path": record["path"],
                            "recorded_at": record.get("recorded_at"),
                            "location": record.get("location"),
                            "tmk_path": record.get("tmk_path"),
                            "tmk_marker_count": record.get("tmk_marker_count"),
                            "tmk_last_marker_seconds": record.get(
                                "tmk_last_marker_seconds"
                            ),
                        }
                    )
                    atomic_json_write(output, result)
                    atomic_text_write(text_output, result["text"].strip() + "\n")
                    completed += 1
                    status = "completed"
            except Exception as exc:  # one corrupt recording must not discard the batch
                failed += 1
                status = "failed"
                failures.append({"path": record["path"], "error": str(exc)})
            if progress:
                progress(index, len(records), record["path"], status)
        rebuild_manifest_summary(manifest)
        atomic_json_write(self.state_dir / "inventory.json", manifest)
        summary = {
            "schema_version": 1,
            "accelerator": transcriber.accelerator,
            "model": transcriber.model,
            "unique_recordings": len(records),
            "completed": completed,
            "cached": skipped,
            "failed": failed,
            "failures": failures,
        }
        atomic_json_write(self.state_dir / "transcription-run.json", summary)
        return summary

    def hydrate_tmk_metadata(
        self,
        *,
        workers: int = 4,
        inspect_timeout_seconds: float = 60,
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Hash Sony TMK sidecars concurrently and checkpoint their markers once."""

        if workers < 1:
            raise ValueError("TMK hydration workers must be at least 1")
        manifest = self._load_inventory()
        records = [
            record
            for record in manifest["files"]
            if record["kind"] == "tmk"
            and (not record.get("sha256") or record.get("tmk_marker_count") is None)
        ]
        completed = failed = 0
        failures = []

        def inspect_one(record: dict[str, Any]) -> dict[str, Any]:
            """Fetch and inspect one unresolved TMK record in an isolated worker."""

            source = self.root / record["path"]
            dataless = not record.get("materialized", False) or is_icloud_dataless(
                source
            )
            staged_path: Path | None = None
            try:
                if dataless:
                    ensure_staging_capacity(
                        self.staging_dir, int(record.get("size_bytes", 0))
                    )
                    staged = self.backend.stage(
                        self.root,
                        record["path"],
                        self.staging_dir,
                        timeout_seconds=inspect_timeout_seconds,
                    )
                    staged_path = Path(staged["staged_path"])
                    inspected = staged["record"]
                else:
                    inspected = self.backend.inspect(
                        self.root,
                        record["path"],
                        timeout_seconds=inspect_timeout_seconds,
                    )
                inspected["materialized"] = not is_icloud_dataless(source)
                return inspected
            finally:
                if staged_path is not None:
                    remove_staged_file(self.staging_dir, staged_path)

        if records:
            with ThreadPoolExecutor(max_workers=min(workers, len(records))) as executor:
                futures = {
                    executor.submit(inspect_one, record): record for record in records
                }
                for index, future in enumerate(as_completed(futures), start=1):
                    record = futures[future]
                    status = "failed"
                    try:
                        record.update(future.result())
                        record["error"] = None
                        for audio_record in manifest["files"]:
                            if (
                                audio_record["kind"] == "audio"
                                and audio_record.get("tmk_path") == record["path"]
                            ):
                                audio_record["tmk_marker_count"] = record.get(
                                    "tmk_marker_count"
                                )
                                audio_record["tmk_last_marker_seconds"] = record.get(
                                    "tmk_last_marker_seconds"
                                )
                                audio_sha256 = audio_record.get("sha256")
                                transcript_path = (
                                    safe_transcript_path(
                                        self.state_dir / "transcripts", audio_sha256
                                    )
                                    if audio_sha256
                                    else None
                                )
                                if transcript_path and transcript_path.is_file():
                                    transcript = json.loads(
                                        transcript_path.read_text(encoding="utf-8")
                                    )
                                    transcript["tmk_marker_count"] = record.get(
                                        "tmk_marker_count"
                                    )
                                    transcript["tmk_last_marker_seconds"] = record.get(
                                        "tmk_last_marker_seconds"
                                    )
                                    atomic_json_write(transcript_path, transcript)
                        completed += 1
                        status = "completed"
                    except Exception as exc:
                        failed += 1
                        record["error"] = str(exc)
                        failures.append({"path": record["path"], "error": str(exc)})
                    finally:
                        rebuild_manifest_summary(manifest)
                        atomic_json_write(self.state_dir / "inventory.json", manifest)
                    if progress:
                        progress(index, len(records), record["path"], status)
        summary = {
            "schema_version": 1,
            "mode": "tmk_hydration",
            "selected": len(records),
            "completed": completed,
            "failed": failed,
            "failures": failures,
        }
        atomic_json_write(self.state_dir / "tmk-hydration-run.json", summary)
        return summary

    def stream_transcribe(
        self,
        config: TranscriptionConfig = TranscriptionConfig(),
        *,
        max_files: int | None = None,
        relative_paths: Iterable[str] | None = None,
        inspect_timeout_seconds: float = 14_400,
        stage_stall_timeout_seconds: float = DEFAULT_STAGE_STALL_TIMEOUT_SECONDS,
        prefetch_workers: int = 1,
        prefetch_max_bytes: int = DEFAULT_PREFETCH_MAX_BYTES,
        evict_after: bool = True,
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Hash and transcribe iCloud files with bounded parallel staging."""

        if prefetch_workers < 1:
            raise ValueError("prefetch workers must be at least 1")
        if prefetch_max_bytes < 1:
            raise ValueError("prefetch max bytes must be positive")

        manifest = self._load_inventory()
        records_by_path = {record["path"]: record for record in manifest["files"]}
        audio_records = [
            record for record in manifest["files"] if record["kind"] == "audio"
        ]
        runtime_dataless = {
            record["path"]: is_icloud_dataless(self.root / record["path"])
            for record in audio_records
        }
        records = sorted(
            audio_records,
            key=lambda record: (
                runtime_dataless[record["path"]],
                record.get("recorded_at") or "9999",
                record["path"],
            ),
        )
        requested_paths = set(relative_paths or [])
        if requested_paths:
            available_paths = {record["path"] for record in records}
            missing_paths = requested_paths - available_paths
            if missing_paths:
                raise ValueError(
                    f"audio paths are absent from inventory: {', '.join(sorted(missing_paths))}"
                )
            records = [
                record for record in records if record["path"] in requested_paths
            ]
        if max_files is not None:
            records = records[:max_files]
        transcriber = GpuTranscriber(config)
        transcript_dir = self.state_dir / "transcripts"
        prefetch_futures: dict[str, Future[dict[str, Any]]] = {}
        prefetch_bytes = 0
        candidates: list[dict[str, Any]] = []
        if prefetch_workers > 1:
            for record in records:
                if not runtime_dataless[record["path"]]:
                    continue
                size_bytes = max(0, int(record.get("size_bytes", 0)))
                if prefetch_bytes + size_bytes > prefetch_max_bytes:
                    continue
                candidates.append(record)
                prefetch_bytes += size_bytes
            if candidates:
                ensure_staging_capacity(self.staging_dir, prefetch_bytes)
                executor = ThreadPoolExecutor(
                    max_workers=min(prefetch_workers, len(candidates))
                )
                try:
                    prefetch_futures = {
                        record["path"]: executor.submit(
                            self.backend.stage,
                            self.root,
                            record["path"],
                            self.staging_dir,
                            timeout_seconds=stage_stall_timeout_seconds,
                        )
                        for record in candidates
                    }
                finally:
                    # Futures keep running after shutdown(wait=False). Retaining them
                    # lets the ordered GPU loop consume the first ready recording
                    # while the bounded worker pool continues staging later files.
                    executor.shutdown(wait=False)
        prefetch_fallback_attempted = prefetch_fallback_recovered = 0
        prefetch_fallback_suppressed = 0
        prefetch_fallback_allowed = True
        prefetch_transcription_overlaps = 0
        completed = cached = failed = 0
        failures = []
        eviction_failures = []
        deferred_evictions: list[dict[str, Any]] = []

        def await_pending_prefetches() -> None:
            """Drain the bounded pool before any out-of-pool serial stage."""

            for pending in prefetch_futures.values():
                try:
                    pending.result()
                except Exception:
                    pass

        def evict_materialized(record: dict[str, Any]) -> None:
            """Release local blocks without changing a durable transcript outcome."""

            try:
                eviction = self.backend.evict(self.root, record["path"])
                if not eviction.get("evicted", False):
                    raise RuntimeError(
                        "native iCloud eviction returned without confirmation"
                    )
            except Exception as exc:
                record["materialized"] = not is_icloud_dataless(
                    self.root / record["path"]
                )
                if record["materialized"]:
                    record["eviction_error"] = str(exc)
                    eviction_failures.append(
                        {"path": record["path"], "error": str(exc)}
                    )
            else:
                record["materialized"] = False
                record.pop("eviction_error", None)

        for index, record in enumerate(records, start=1):
            audio_path = self.root / record["path"]
            audio_input = audio_path
            staged_audio: Path | None = None
            was_dataless = record["path"] in prefetch_futures or is_icloud_dataless(
                audio_path
            )
            status = "failed"
            try:
                tmk_path = record.get("tmk_path")
                tmk_record = records_by_path.get(tmk_path, {}) if tmk_path else {}
                tmk_needs_metadata = bool(
                    tmk_path
                    and (
                        not tmk_record.get("sha256")
                        or tmk_record.get("tmk_marker_count") is None
                    )
                )
                if tmk_path:
                    if tmk_needs_metadata:
                        record["tmk_error"] = tmk_record.get("error") or (
                            "TMK metadata unresolved; run hydrate-tmk before "
                            "stream-transcribe"
                        )
                    else:
                        record.pop("tmk_error", None)
                    record["tmk_marker_count"] = tmk_record.get("tmk_marker_count")
                    record["tmk_last_marker_seconds"] = tmk_record.get(
                        "tmk_last_marker_seconds"
                    )
                known_sha256 = record.get("sha256")
                if was_dataless:
                    preserved_tmk = {
                        "tmk_path": record.get("tmk_path"),
                        "tmk_marker_count": record.get("tmk_marker_count"),
                        "tmk_last_marker_seconds": record.get(
                            "tmk_last_marker_seconds"
                        ),
                        "tmk_error": record.get("tmk_error"),
                    }
                    prefetch_future = prefetch_futures.pop(record["path"], None)
                    staged: dict[str, Any] | Exception | None = None
                    if prefetch_future is not None:
                        try:
                            staged = prefetch_future.result()
                        except Exception as exc:
                            staged = exc
                    if isinstance(staged, subprocess.TimeoutExpired):
                        if not prefetch_fallback_allowed:
                            prefetch_fallback_suppressed += 1
                            raise staged
                        prefetch_fallback_attempted += 1
                        # Preserve the existing serial fallback contract: no extra
                        # FileProvider stage starts while bounded prefetch work is
                        # still running. Successful futures can still overlap GPU.
                        await_pending_prefetches()
                        ensure_staging_capacity(
                            self.staging_dir, int(record.get("size_bytes", 0))
                        )
                        try:
                            staged = self.backend.stage(
                                self.root,
                                record["path"],
                                self.staging_dir,
                                timeout_seconds=stage_stall_timeout_seconds,
                            )
                        except Exception:
                            prefetch_fallback_allowed = False
                            raise
                        prefetch_fallback_recovered += 1
                    elif isinstance(staged, Exception):
                        raise staged
                    if staged is None:
                        await_pending_prefetches()
                        ensure_staging_capacity(
                            self.staging_dir, int(record.get("size_bytes", 0))
                        )
                        staged = self.backend.stage(
                            self.root,
                            record["path"],
                            self.staging_dir,
                            timeout_seconds=stage_stall_timeout_seconds,
                        )
                    staged_audio = Path(staged["staged_path"])
                    audio_input = staged_audio
                    inspected = staged["record"]
                    if known_sha256 and inspected.get("sha256") != known_sha256:
                        record["sha256_verified"] = False
                        raise ValueError(
                            f"SHA-256 changed for {record['path']}: "
                            f"expected {known_sha256}, got {inspected.get('sha256')}"
                        )
                    record.update(inspected)
                    record.update(preserved_tmk)
                    record["sha256_verified"] = True
                    record["sha256_source"] = "content"
                    record["materialized"] = not is_icloud_dataless(audio_path)
                else:
                    self._verify_materialized_record(
                        record, timeout_seconds=inspect_timeout_seconds
                    )
                sha256 = validate_sha256(record["sha256"])
                transcript_path = safe_transcript_path(transcript_dir, sha256)
                text_path = safe_transcript_path(transcript_dir, sha256, ".txt")
                if transcript_path.is_file():
                    cached += 1
                    status = "cached"
                else:
                    if any(not pending.done() for pending in prefetch_futures.values()):
                        prefetch_transcription_overlaps += 1
                    result = transcriber.transcribe(audio_input)
                    result.update(
                        {
                            "schema_version": 1,
                            "sha256": sha256,
                            "source_path": record["path"],
                            "recorded_at": record.get("recorded_at"),
                            "location": record.get("location"),
                            "tmk_path": record.get("tmk_path"),
                            "tmk_marker_count": record.get("tmk_marker_count"),
                            "tmk_last_marker_seconds": record.get(
                                "tmk_last_marker_seconds"
                            ),
                            "tmk_error": record.get("tmk_error"),
                        }
                    )
                    atomic_json_write(transcript_path, result)
                    atomic_text_write(text_path, result["text"].strip() + "\n")
                    completed += 1
                    status = "completed"
                record["error"] = None
            except Exception as exc:  # checkpoint the failure and continue the batch
                failed += 1
                record["error"] = str(exc)
                failures.append({"path": record["path"], "error": str(exc)})
            finally:
                if staged_audio is not None:
                    remove_staged_file(self.staging_dir, staged_audio)
                if evict_after and was_dataless and record.get("materialized"):
                    if any(not pending.done() for pending in prefetch_futures.values()):
                        deferred_evictions.append(record)
                    else:
                        evict_materialized(record)
                rebuild_manifest_summary(manifest)
                atomic_json_write(self.state_dir / "inventory.json", manifest)
            if progress:
                progress(index, len(records), record["path"], status)
        for record in deferred_evictions:
            evict_materialized(record)
            rebuild_manifest_summary(manifest)
            atomic_json_write(self.state_dir / "inventory.json", manifest)
        summary = {
            "schema_version": 1,
            "mode": "icloud_streaming",
            "accelerator": transcriber.accelerator,
            "model": transcriber.model,
            "prefetch_workers": prefetch_workers,
            "prefetched": len(candidates),
            "prefetch_bytes": prefetch_bytes,
            "prefetch_fallback_attempted": prefetch_fallback_attempted,
            "prefetch_fallback_recovered": prefetch_fallback_recovered,
            "prefetch_fallback_suppressed": prefetch_fallback_suppressed,
            "prefetch_transcription_overlaps": prefetch_transcription_overlaps,
            "recordings_selected": len(records),
            "completed": completed,
            "cached": cached,
            "failed": failed,
            "failures": failures,
            "eviction_failed": len(eviction_failures),
            "eviction_failures": eviction_failures,
        }
        atomic_json_write(self.state_dir / "streaming-transcription-run.json", summary)
        return summary

    def plan(
        self,
        *,
        allow_missing_transcripts: bool = False,
        defer_unready: bool = False,
    ) -> dict[str, Any]:
        """Create a collision-resistant duplicate quarantine and rename plan."""

        if allow_missing_transcripts and defer_unready:
            raise ValueError(
                "allow_missing_transcripts and defer_unready are mutually exclusive"
            )
        manifest = self._load_inventory()
        records_by_path = {record["path"]: record for record in manifest["files"]}
        earliest_by_hash = {
            group["sha256"]: group.get("earliest_recorded_at")
            for group in manifest["duplicate_groups"]
        }
        operations = []
        moved_tmk: set[str] = set()
        missing = [
            record["path"]
            for record in manifest["files"]
            if record["kind"] == "audio" and not record.get("sha256")
        ]

        for group in manifest["duplicate_groups"]:
            for duplicate in group["duplicate_paths"]:
                record = records_by_path[duplicate]
                if not self._record_ready_for_mutation(record):
                    missing.append(record["path"])
                    continue
                operations.append(
                    mutation(
                        "quarantine",
                        duplicate,
                        quarantine_path(group["sha256"], duplicate),
                        group["sha256"],
                    )
                )
                tmk_path = record.get("tmk_path")
                if tmk_path and tmk_path not in moved_tmk:
                    tmk_record = records_by_path.get(tmk_path)
                    tmk_sha256 = (
                        tmk_record.get("sha256") if tmk_record else group["sha256"]
                    )
                    operations.append(
                        mutation(
                            "quarantine",
                            tmk_path,
                            quarantine_path(tmk_sha256, tmk_path),
                            tmk_record.get("sha256") if tmk_record else None,
                        )
                    )
                    moved_tmk.add(tmk_path)

        for record in unique_audio_records(manifest):
            sha256 = validate_sha256(record["sha256"])
            transcript_path = safe_transcript_path(
                self.state_dir / "transcripts", sha256
            )
            if transcript_path.is_file():
                transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            elif allow_missing_transcripts:
                transcript = {"text": "전사대기", "segments": []}
            elif defer_unready:
                missing.append(record["path"])
                continue
            else:
                missing.append(record["path"])
                continue
            recorded_at = earliest_by_hash.get(sha256) or record.get("recorded_at")
            if not recorded_at:
                raise ValueError(f"recording time is unknown: {record['path']}")
            if is_existing_standard_filename(record, recorded_at):
                destination = record["path"]
            else:
                if not self._record_ready_for_mutation(record):
                    missing.append(record["path"])
                    continue
                destination = str(
                    Path(record["path"]).with_name(
                        standard_filename(record, transcript, recorded_at)
                    )
                )
            if destination != record["path"]:
                operations.append(
                    mutation("rename", record["path"], destination, sha256)
                )
            tmk_path = record.get("tmk_path")
            if tmk_path and tmk_path not in moved_tmk:
                tmk_destination = str(Path(destination).with_suffix(".tmk"))
                if tmk_destination != tmk_path:
                    tmk_record = records_by_path.get(tmk_path)
                    operations.append(
                        mutation(
                            "rename",
                            tmk_path,
                            tmk_destination,
                            tmk_record.get("sha256") if tmk_record else None,
                        )
                    )
                moved_tmk.add(tmk_path)
        if missing and not defer_unready:
            sample = ", ".join(missing[:3])
            raise ValueError(
                f"{len(missing)} transcripts are missing or SHA-256 is unresolved; "
                f"first paths: {sample}"
            )
        rebuild_manifest_summary(manifest)
        atomic_json_write(self.state_dir / "inventory.json", manifest)
        plan = {
            "schema_version": 1,
            "root": str(self.root),
            "inventory_sha256": hashlib.sha256(
                (self.state_dir / "inventory.json").read_bytes()
            ).hexdigest(),
            "operations": operations,
            "deferred_paths": sorted(set(missing)) if defer_unready else [],
        }
        atomic_json_write(self.state_dir / "mutation-plan.json", plan)
        return plan

    def apply(self, *, execute: bool = False) -> dict[str, Any]:
        """Validate by default, or execute only when explicitly requested."""

        self._validate_mutation_plan()
        return self.backend.apply(
            self.state_dir / "mutation-plan.json",
            self.state_dir / "mutation-journal.json",
            execute=execute,
        )

    def _ensure_secure_state_dir(self) -> None:
        """Keep all durable state in a real owner-only child of the library root."""

        if self.state_dir.is_symlink():
            raise ValueError(f"state directory must not be a symlink: {self.state_dir}")
        ensure_private_directory(self.state_dir)
        if self.state_dir.resolve() != self.root / ".codec-carver":
            raise ValueError("state directory escaped the library root")

    def _verify_materialized_record(
        self, record: dict[str, Any], *, timeout_seconds: float = 14_400
    ) -> None:
        """Rehash the exact current local bytes before cache or GPU use."""

        source = self.root / record["path"]
        if not source.is_file() or is_icloud_dataless(source):
            raise ValueError(
                f"recording is not materialized; use stream-transcribe: {record['path']}"
            )
        expected = record.get("sha256")
        inspected = self.backend.inspect(
            self.root, record["path"], timeout_seconds=timeout_seconds
        )
        actual = validate_sha256(inspected.get("sha256"), label="inspected SHA-256")
        if expected and actual != validate_sha256(expected):
            record["sha256_verified"] = False
            record["error"] = (
                f"SHA-256 changed for {record['path']}: expected {expected}, got {actual}"
            )
            raise ValueError(record["error"])
        preserved = {
            key: record.get(key)
            for key in (
                "tmk_path",
                "tmk_marker_count",
                "tmk_last_marker_seconds",
                "tmk_error",
            )
        }
        record.update(inspected)
        record.update(preserved)
        record["sha256"] = actual
        record["sha256_verified"] = True
        record["sha256_source"] = "content"
        record["materialized"] = True
        record["error"] = None

    def _record_ready_for_mutation(self, record: dict[str, Any]) -> bool:
        """Verify local bytes now, or require prior content-bound staging evidence."""

        source = self.root / record["path"]
        if source.is_file() and not is_icloud_dataless(source):
            self._verify_materialized_record(record)
            return True
        return record_sha_is_verified(record)

    def _validate_mutation_plan(self) -> None:
        """Reject a tampered plan before it reaches even a mocked/native backend."""

        self._ensure_secure_state_dir()
        plan_path = self.state_dir / "mutation-plan.json"
        if not plan_path.is_file():
            raise FileNotFoundError(
                f"mutation plan not found: {plan_path}; call plan() first"
            )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("root") != str(self.root):
            raise ValueError("mutation plan root does not match the audio library")
        inventory_path = self.state_dir / "inventory.json"
        inventory_sha256 = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
        if plan.get("inventory_sha256") != inventory_sha256:
            raise ValueError("inventory changed after mutation plan generation")
        operations = plan.get("operations")
        if not isinstance(operations, list):
            raise ValueError("mutation plan operations must be a list")
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict) or operation.get("action") not in {
                "rename",
                "quarantine",
            }:
                raise ValueError(f"invalid mutation operation at index {index}")
            operation["source"] = validate_relative_path(
                self.root,
                operation.get("source"),
                label=f"mutation source {index}",
            )
            operation["destination"] = validate_relative_path(
                self.root,
                operation.get("destination"),
                label=f"mutation destination {index}",
            )
            if operation.get("sha256") is not None:
                validate_sha256(operation["sha256"], label=f"mutation SHA-256 {index}")

    def _load_inventory(self) -> dict[str, Any]:
        """Load the previously generated inventory or fail with a precise instruction."""

        self._ensure_secure_state_dir()
        path = self.state_dir / "inventory.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"inventory not found: {path}; call inventory() first"
            )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest_root = manifest.get("root")
        if (
            manifest_root is not None
            and Path(str(manifest_root)).resolve() != self.root
        ):
            raise ValueError("inventory root does not match the audio library")
        files = manifest.get("files")
        if not isinstance(files, list):
            raise ValueError("inventory files must be a list")
        records_by_path: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(files):
            if not isinstance(record, dict):
                raise ValueError(f"inventory record {index} must be an object")
            record["path"] = validate_relative_path(
                self.root, record.get("path"), label=f"inventory path {index}"
            )
            if record.get("kind") not in {"audio", "tmk"}:
                raise ValueError(f"inventory record {index} has an invalid kind")
            if record["path"] in records_by_path:
                raise ValueError(f"duplicate inventory path: {record['path']}")
            if record.get("sha256"):
                validate_sha256(record["sha256"], label=f"inventory SHA-256 {index}")
            if record.get("tmk_path"):
                record["tmk_path"] = validate_relative_path(
                    self.root,
                    record["tmk_path"],
                    label=f"inventory TMK path {index}",
                )
            records_by_path[record["path"]] = record
        duplicate_groups = manifest.get("duplicate_groups")
        if not isinstance(duplicate_groups, list):
            raise ValueError("inventory duplicate_groups must be a list")
        for index, group in enumerate(duplicate_groups):
            if not isinstance(group, dict):
                raise ValueError(f"duplicate group {index} must be an object")
            sha256 = validate_sha256(
                group.get("sha256"), label=f"duplicate group SHA-256 {index}"
            )
            duplicate_paths = group.get("duplicate_paths")
            if not isinstance(duplicate_paths, list):
                raise ValueError(f"duplicate group {index} paths must be a list")
            paths = [group.get("canonical_path"), *duplicate_paths]
            for value in paths:
                normalized = validate_relative_path(
                    self.root, value, label=f"duplicate group path {index}"
                )
                record = records_by_path.get(normalized)
                if record is None or record.get("sha256") != sha256:
                    raise ValueError(
                        f"duplicate group {index} is not bound to matching inventory records"
                    )
        return manifest


def unique_audio_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one canonical, hashable audio record for each content hash."""

    canonical = {
        group["sha256"]: group["canonical_path"]
        for group in manifest["duplicate_groups"]
    }
    seen = set()
    records = []
    for record in sorted(
        (
            item
            for item in manifest["files"]
            if item["kind"] == "audio" and item.get("sha256")
        ),
        key=lambda item: (item.get("recorded_at") or "9999", item["path"]),
    ):
        sha256 = record["sha256"]
        if sha256 in seen or canonical.get(sha256, record["path"]) != record["path"]:
            continue
        seen.add(sha256)
        records.append(record)
    return records


def record_sha_is_verified(record: dict[str, Any]) -> bool:
    """Distinguish current/content-bound hashes from placeholder-only hints."""

    explicit = record.get("sha256_verified")
    if isinstance(explicit, bool):
        return explicit
    return bool(record.get("sha256")) and record.get("sha256_source") not in {
        "previous_inventory",
        "transcript_sidecar",
    }


def rebuild_manifest_summary(manifest: dict[str, Any]) -> None:
    """Recompute duplicate and materialization summaries after a streaming checkpoint."""

    audio_records = [
        record for record in manifest["files"] if record["kind"] == "audio"
    ]
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for record in audio_records:
        if record.get("sha256") and record_sha_is_verified(record):
            by_hash.setdefault(record["sha256"], []).append(record)
    groups = []
    copy_suffix = re.compile(r"(?i)(?:\s*\(\d+\)|\s+\d+)$")
    for sha256, records in sorted(by_hash.items()):
        if len(records) < 2:
            continue
        records.sort(
            key=lambda record: (
                record.get("recorded_at") or "9999",
                bool(copy_suffix.search(Path(record["path"]).stem)),
                not bool(record.get("tmk_path")),
                not bool(record.get("location")),
                len(Path(record["path"]).parts),
                record["path"],
            )
        )
        groups.append(
            {
                "sha256": sha256,
                "size_bytes": records[0]["size_bytes"],
                "canonical_path": records[0]["path"],
                "duplicate_paths": [record["path"] for record in records[1:]],
                "earliest_recorded_at": min(
                    (
                        record["recorded_at"]
                        for record in records
                        if record.get("recorded_at")
                    ),
                    default=None,
                ),
            }
        )
    manifest["duplicate_groups"] = groups
    manifest["dataless_file_count"] = sum(
        not record.get("materialized", False) for record in manifest["files"]
    )
    manifest["earliest_recording_at"] = min(
        (
            record["recorded_at"]
            for record in audio_records
            if record.get("recorded_at")
        ),
        default=None,
    )
    manifest["errors"] = [
        f"{record['path']}: {record['error']}"
        for record in manifest["files"]
        if record.get("error")
    ]


def is_icloud_dataless(path: Path) -> bool:
    """Return whether macOS currently marks a file as an evicted iCloud placeholder."""

    if platform.system() != "Darwin":
        return False
    try:
        flags = path.stat().st_flags
    except FileNotFoundError:
        return False
    return bool(flags & MACOS_SF_DATALESS)


def ensure_staging_capacity(staging_dir: Path, size_bytes: int) -> None:
    """Reserve enough local scratch for one recording plus a fixed safety margin."""

    ensure_private_directory(staging_dir)
    required = max(0, size_bytes) + 512 * 1024 * 1024
    available = shutil.disk_usage(staging_dir).free
    if available < required:
        raise OSError(
            f"insufficient staging space: need {required} bytes, have {available} bytes"
        )


def remove_staged_file(staging_dir: Path, staged_path: Path) -> None:
    """Delete one direct child relative to a no-follow scratch directory handle."""

    root = staging_dir.absolute()
    candidate = staged_path.absolute()
    if candidate.parent != root or candidate.name in {"", ".", ".."}:
        raise ValueError(f"staged path escaped scratch root: {candidate}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, flags)
    try:
        try:
            metadata = os.stat(
                candidate.name, dir_fd=directory_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"staged artifact is not a regular file: {candidate.name}")
        os.unlink(candidate.name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def restore_inventory_evidence(
    manifest: dict[str, Any],
    state_dir: Path,
    *,
    previous_manifest: dict[str, Any] | None = None,
) -> int:
    """Restore journaled or sidecar-backed SHA evidence after placeholder rescans."""

    journal_sha: dict[str, str] = {}
    journal_path = state_dir / "mutation-journal.json"
    if journal_path.is_file():
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("executed"):
            journal_sha = {
                operation["destination"]: operation["sha256"]
                for operation in journal.get("completed", [])
                if operation.get("sha256")
                and SHA256_RE.fullmatch(str(operation["sha256"]))
            }
    transcript_dir = state_dir / "transcripts"
    transcript_hashes = {
        path.stem
        for path in transcript_dir.glob("*.json")
        if re.fullmatch(r"[0-9a-f]{64}", path.stem)
    }
    previous_by_path = {
        record["path"]: record for record in (previous_manifest or {}).get("files", [])
    }
    restored = 0
    for record in manifest["files"]:
        if record.get("sha256"):
            record.setdefault("sha256_verified", True)
        if not record.get("sha256"):
            sha256 = journal_sha.get(record["path"])
            source = "mutation_journal"
            if not sha256:
                match = STANDARD_SHA_RE.search(Path(record["path"]).name)
                matches = (
                    sorted(
                        value
                        for value in transcript_hashes
                        if value.startswith(match.group("prefix"))
                    )
                    if match
                    else []
                )
                sha256 = matches[0] if len(matches) == 1 else None
                source = "transcript_sidecar"
            if not sha256:
                previous = previous_by_path.get(record["path"], {})
                if previous.get("sha256") and previous.get("size_bytes") == record.get(
                    "size_bytes"
                ):
                    sha256 = previous["sha256"]
                    source = "previous_inventory"
            if sha256:
                record["sha256"] = sha256
                record["sha256_source"] = source
                record["sha256_verified"] = source == "mutation_journal"
                restored += 1
        if (
            record["kind"] != "audio"
            or not record.get("sha256")
            or not record_sha_is_verified(record)
        ):
            continue
        transcript_path = safe_transcript_path(transcript_dir, record["sha256"])
        if not transcript_path.is_file():
            continue
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        transcript["source_path"] = record["path"]
        transcript["recorded_at"] = record.get("recorded_at")
        if record.get("location"):
            transcript["location"] = record["location"]
        transcript["tmk_path"] = record.get("tmk_path")
        transcript["tmk_marker_count"] = record.get("tmk_marker_count")
        transcript["tmk_last_marker_seconds"] = record.get("tmk_last_marker_seconds")
        atomic_json_write(transcript_path, transcript)
    rebuild_manifest_summary(manifest)
    manifest["restored_sha256_count"] = restored
    return restored


def quarantine_path(sha256: str, source: str) -> str:
    """Preserve the original relative hierarchy under the recovery area."""

    validate_sha256(sha256, label="quarantine SHA-256")
    if not isinstance(source, str) or not source or "\x00" in source or "\\" in source:
        raise ValueError("quarantine source must be a non-empty portable path")
    source_path = Path(source)
    if source_path.is_absolute() or any(
        part in {"", ".", ".."} for part in source_path.parts
    ):
        raise ValueError(f"quarantine source must be relative: {source!r}")
    return str(
        Path(".codec-carver") / "quarantine" / "exact-duplicates" / sha256 / source_path
    )


def mutation(
    action: str, source: str, destination: str, sha256: str | None
) -> dict[str, Any]:
    """Build one Rust mutation record."""

    return {
        "action": action,
        "source": source,
        "destination": destination,
        "sha256": sha256,
    }


def progress_line(index: int, total: int, path: str, status: str) -> None:
    """Print a compact, flush-safe CLI progress record."""

    print(f"TRANSCRIBE\t{index}/{total}\t{status}\t{path}", flush=True)


def tmk_progress_line(index: int, total: int, path: str, status: str) -> None:
    """Print a compact, flush-safe TMK metadata progress record."""

    print(f"TMK\t{index}/{total}\t{status}\t{path}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line adapter around the Python API."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--backend-binary", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--threads", type=int)
    tmk_parser = subparsers.add_parser("hydrate-tmk")
    tmk_parser.add_argument("--workers", type=int, default=4)
    tmk_parser.add_argument("--inspect-timeout-seconds", type=float, default=60)
    transcribe_parser = subparsers.add_parser("transcribe")
    transcribe_parser.add_argument(
        "--accelerator", choices=["auto", "mlx", "cuda"], default="auto"
    )
    transcribe_parser.add_argument("--model")
    transcribe_parser.add_argument("--language", default="ko")
    transcribe_parser.add_argument("--max-files", type=int)
    transcribe_parser.add_argument("--word-timestamps", action="store_true")
    stream_parser = subparsers.add_parser("stream-transcribe")
    stream_parser.add_argument(
        "--accelerator", choices=["auto", "mlx", "cuda"], default="auto"
    )
    stream_parser.add_argument("--model")
    stream_parser.add_argument("--language", default="ko")
    stream_parser.add_argument("--max-files", type=int)
    stream_parser.add_argument("--path", action="append", default=[])
    stream_parser.add_argument("--inspect-timeout-seconds", type=float, default=14_400)
    stream_parser.add_argument(
        "--stage-stall-timeout-seconds",
        type=float,
        default=DEFAULT_STAGE_STALL_TIMEOUT_SECONDS,
    )
    stream_parser.add_argument("--prefetch-workers", type=int, default=1)
    stream_parser.add_argument(
        "--prefetch-max-bytes", type=int, default=DEFAULT_PREFETCH_MAX_BYTES
    )
    stream_parser.add_argument("--keep-local", action="store_true")
    stream_parser.add_argument("--word-timestamps", action="store_true")
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--allow-missing-transcripts", action="store_true")
    plan_parser.add_argument("--defer-unready", action="store_true")
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """Run inventory, GPU transcription, planning, or guarded application."""

    args = build_parser().parse_args(argv)
    library = AudioLibrary(args.root, RustBackend(args.backend_binary))
    if args.command == "inventory":
        result = library.inventory(threads=args.threads)
    elif args.command == "hydrate-tmk":
        result = library.hydrate_tmk_metadata(
            workers=args.workers,
            inspect_timeout_seconds=args.inspect_timeout_seconds,
            progress=tmk_progress_line,
        )
    elif args.command == "transcribe":
        result = library.transcribe(
            TranscriptionConfig(
                accelerator=args.accelerator,
                model=args.model,
                language=args.language or None,
                word_timestamps=args.word_timestamps,
            ),
            max_files=args.max_files,
            progress=progress_line,
        )
    elif args.command == "stream-transcribe":
        result = library.stream_transcribe(
            TranscriptionConfig(
                accelerator=args.accelerator,
                model=args.model,
                language=args.language or None,
                word_timestamps=args.word_timestamps,
            ),
            max_files=args.max_files,
            relative_paths=args.path,
            inspect_timeout_seconds=args.inspect_timeout_seconds,
            stage_stall_timeout_seconds=args.stage_stall_timeout_seconds,
            prefetch_workers=args.prefetch_workers,
            prefetch_max_bytes=args.prefetch_max_bytes,
            evict_after=not args.keep_local,
            progress=progress_line,
        )
    elif args.command == "plan":
        result = library.plan(
            allow_missing_transcripts=args.allow_missing_transcripts,
            defer_unready=args.defer_unready,
        )
    else:
        result = library.apply(execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("failed", 0) else 0


if __name__ == "__main__":  # pragma: no cover - exercised through the installed CLI
    raise SystemExit(main())
