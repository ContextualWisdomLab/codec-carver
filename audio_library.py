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
import platform
import re
import shutil
import subprocess
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-turbo-q4"
DEFAULT_CUDA_MODEL = "large-v3-turbo"
MACOS_SF_DATALESS = 0x40000000
MIN_TRANSCRIBABLE_SECONDS = 0.5
STANDARD_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:__[^/]+)*__sha256-[0-9a-f]{12}$"
)
FILLER_RE = re.compile(r"\b(?:어|음|아|그|저기|그러니까|뭐지)\b[,.!?\s]*")
SPACE_RE = re.compile(r"\s+")
UNSAFE_NAME_RE = re.compile(r"[^0-9A-Za-z가-힣._-]+")


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
            candidates.append(Path(binary))
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
        installed = shutil.which("codec-carver-core")
        if installed:
            candidates.append(Path(installed))
        self.binary = next(
            (candidate for candidate in candidates if candidate.is_file()), None
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
    ) -> dict[str, Any]:
        """Stream one placeholder while timing out only sustained zero progress."""

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
        return self._run_stage_json(
            command,
            staging_dir,
            stall_timeout_seconds=timeout_seconds,
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
                for partial in staging_dir.glob(pattern):
                    partial.unlink(missing_ok=True)
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
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        completed = subprocess.run(
            [
                ffprobe,
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


def transcript_description(transcript: dict[str, Any], *, limit: int = 48) -> str:
    """Derive a deterministic filename description from early transcript content."""

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
    meaningful = [value for value in cleaned if len(value) >= 4]
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


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON through a same-directory temporary file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


class AudioLibrary:
    """Public Python API for the end-to-end curation workflow."""

    def __init__(self, root: Path | str, backend: RustBackend | None = None) -> None:
        """Bind the API to one library root and one Rust backend."""

        self.root = Path(root).resolve()
        self.state_dir = self.root / ".codec-carver"
        root_key = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16]
        self.staging_dir = (
            Path(tempfile.gettempdir()).resolve() / "codec-carver-staging" / root_key
        )
        self.backend = backend or RustBackend()

    def inventory(self, *, threads: int | None = None) -> dict[str, Any]:
        """Generate the canonical SHA-256/TMK inventory."""

        return self.backend.inventory(
            self.root,
            self.state_dir / "inventory.json",
            threads=threads,
        )

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
            sha256 = record["sha256"]
            output = transcript_dir / f"{sha256}.json"
            if output.is_file():
                skipped += 1
                if progress:
                    progress(index, len(records), record["path"], "cached")
                continue
            try:
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
                (transcript_dir / f"{sha256}.txt").write_text(
                    result["text"].strip() + "\n", encoding="utf-8"
                )
                completed += 1
                status = "completed"
            except Exception as exc:  # one corrupt recording must not discard the batch
                failed += 1
                status = "failed"
                failures.append({"path": record["path"], "error": str(exc)})
            if progress:
                progress(index, len(records), record["path"], status)
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
                                transcript_path = (
                                    self.state_dir
                                    / "transcripts"
                                    / f"{audio_record.get('sha256')}.json"
                                )
                                if (
                                    audio_record.get("sha256")
                                    and transcript_path.is_file()
                                ):
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
        stage_stall_timeout_seconds: float = 120,
        evict_after: bool = True,
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Hash and transcribe one iCloud file at a time with durable checkpoints."""

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
        completed = cached = failed = 0
        failures = []
        for index, record in enumerate(records, start=1):
            audio_path = self.root / record["path"]
            audio_input = audio_path
            staged_audio: Path | None = None
            was_dataless = is_icloud_dataless(audio_path)
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
                known_transcript = (
                    transcript_dir / f"{known_sha256}.json" if known_sha256 else None
                )
                if was_dataless and not (
                    known_transcript and known_transcript.is_file()
                ):
                    ensure_staging_capacity(
                        self.staging_dir, int(record.get("size_bytes", 0))
                    )
                    preserved_tmk = {
                        "tmk_path": record.get("tmk_path"),
                        "tmk_marker_count": record.get("tmk_marker_count"),
                        "tmk_last_marker_seconds": record.get(
                            "tmk_last_marker_seconds"
                        ),
                        "tmk_error": record.get("tmk_error"),
                    }
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
                        raise ValueError(
                            f"SHA-256 changed for {record['path']}: "
                            f"expected {known_sha256}, got {inspected.get('sha256')}"
                        )
                    record.update(inspected)
                    record.update(preserved_tmk)
                    record["materialized"] = not is_icloud_dataless(audio_path)
                elif not record.get("sha256"):
                    preserved_tmk = {
                        "tmk_path": record.get("tmk_path"),
                        "tmk_marker_count": record.get("tmk_marker_count"),
                        "tmk_last_marker_seconds": record.get(
                            "tmk_last_marker_seconds"
                        ),
                        "tmk_error": record.get("tmk_error"),
                    }
                    record.update(
                        self.backend.inspect(
                            self.root,
                            record["path"],
                            timeout_seconds=inspect_timeout_seconds,
                        )
                    )
                    record.update(preserved_tmk)
                sha256 = record["sha256"]
                transcript_path = transcript_dir / f"{sha256}.json"
                if transcript_path.is_file():
                    cached += 1
                    status = "cached"
                else:
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
                    (transcript_dir / f"{sha256}.txt").write_text(
                        result["text"].strip() + "\n", encoding="utf-8"
                    )
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
                    evict_icloud_file(self.root / record["path"])
                    record["materialized"] = False
                rebuild_manifest_summary(manifest)
                atomic_json_write(self.state_dir / "inventory.json", manifest)
            if progress:
                progress(index, len(records), record["path"], status)
        summary = {
            "schema_version": 1,
            "mode": "icloud_streaming",
            "accelerator": transcriber.accelerator,
            "model": transcriber.model,
            "recordings_selected": len(records),
            "completed": completed,
            "cached": cached,
            "failed": failed,
            "failures": failures,
        }
        atomic_json_write(self.state_dir / "streaming-transcription-run.json", summary)
        return summary

    def plan(self, *, allow_missing_transcripts: bool = False) -> dict[str, Any]:
        """Create a collision-resistant duplicate quarantine and rename plan."""

        manifest = self._load_inventory()
        records_by_path = {record["path"]: record for record in manifest["files"]}
        earliest_by_hash = {
            group["sha256"]: group.get("earliest_recorded_at")
            for group in manifest["duplicate_groups"]
        }
        operations = []
        moved_tmk: set[str] = set()

        for group in manifest["duplicate_groups"]:
            for duplicate in group["duplicate_paths"]:
                record = records_by_path[duplicate]
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

        missing = []
        for record in unique_audio_records(manifest):
            sha256 = record["sha256"]
            transcript_path = self.state_dir / "transcripts" / f"{sha256}.json"
            if transcript_path.is_file():
                transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            elif allow_missing_transcripts:
                transcript = {"text": "전사대기", "segments": []}
            else:
                missing.append(record["path"])
                continue
            recorded_at = earliest_by_hash.get(sha256) or record.get("recorded_at")
            if not recorded_at:
                raise ValueError(f"recording time is unknown: {record['path']}")
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
        if missing:
            sample = ", ".join(missing[:3])
            raise ValueError(
                f"{len(missing)} transcripts are missing; first paths: {sample}"
            )
        plan = {
            "schema_version": 1,
            "root": str(self.root),
            "inventory_sha256": hashlib.sha256(
                (self.state_dir / "inventory.json").read_bytes()
            ).hexdigest(),
            "operations": operations,
        }
        atomic_json_write(self.state_dir / "mutation-plan.json", plan)
        return plan

    def apply(self, *, execute: bool = False) -> dict[str, Any]:
        """Validate by default, or execute only when explicitly requested."""

        return self.backend.apply(
            self.state_dir / "mutation-plan.json",
            self.state_dir / "mutation-journal.json",
            execute=execute,
        )

    def _load_inventory(self) -> dict[str, Any]:
        """Load the previously generated inventory or fail with a precise instruction."""

        path = self.state_dir / "inventory.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"inventory not found: {path}; call inventory() first"
            )
        return json.loads(path.read_text(encoding="utf-8"))


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


def rebuild_manifest_summary(manifest: dict[str, Any]) -> None:
    """Recompute duplicate and materialization summaries after a streaming checkpoint."""

    audio_records = [
        record for record in manifest["files"] if record["kind"] == "audio"
    ]
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for record in audio_records:
        if record.get("sha256"):
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


def evict_icloud_file(path: Path) -> None:
    """Release a streamed iCloud file's local blocks after its durable checkpoint."""

    if platform.system() != "Darwin":
        return
    brctl = shutil.which("brctl")
    if not brctl:
        raise FileNotFoundError("brctl is required to evict streamed iCloud files")
    subprocess.run(
        [brctl, "evict", str(path)],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=300,
    )


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

    staging_dir.mkdir(parents=True, exist_ok=True)
    required = max(0, size_bytes) + 512 * 1024 * 1024
    available = shutil.disk_usage(staging_dir).free
    if available < required:
        raise OSError(
            f"insufficient staging space: need {required} bytes, have {available} bytes"
        )


def remove_staged_file(staging_dir: Path, staged_path: Path) -> None:
    """Delete only a Rust-produced file contained by the configured scratch root."""

    root = staging_dir.resolve()
    candidate = staged_path.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"staged path escaped scratch root: {candidate}")
    candidate.unlink(missing_ok=True)


def quarantine_path(sha256: str, source: str) -> str:
    """Preserve the original relative hierarchy under the recovery area."""

    return str(
        Path(".codec-carver") / "quarantine" / "exact-duplicates" / sha256 / source
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
    stream_parser.add_argument("--stage-stall-timeout-seconds", type=float, default=120)
    stream_parser.add_argument("--keep-local", action="store_true")
    stream_parser.add_argument("--word-timestamps", action="store_true")
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--allow-missing-transcripts", action="store_true")
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
            evict_after=not args.keep_local,
            progress=progress_line,
        )
    elif args.command == "plan":
        result = library.plan(allow_missing_transcripts=args.allow_missing_transcripts)
    else:
        result = library.apply(execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the installed CLI
    raise SystemExit(main())
