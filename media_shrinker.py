#!/usr/bin/env python3
"""Shrink large media files below a target size while preserving metadata.

The tool is intentionally conservative: it never overwrites or deletes source
files, can prefer lossless FLAC for all audio to avoid extra loss, falls back to
high-bitrate Opus when required by size constraints, and restores filesystem
metadata on generated files.
"""

import argparse
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_EXTENSIONS = {
    ".3gp",
    ".3gpp",
    ".ac3",
    ".aiff",
    ".amr",
    ".au",
    ".flac",
    ".m4a",
    ".mid",
    ".mp3",
    ".mxf",
    ".opus",
    ".ra",
    ".wav",
    ".weba",
    ".aac",
    ".asx",
    ".avi",
    ".ogm",
    ".ogv",
    ".m4v",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".wmv",
    ".webm",
}

SUPPORTED_EXTS_TUPLE = tuple(SUPPORTED_EXTENSIONS)

LOSSLESS_AUDIO_CODECS = {
    "alac",
    "flac",
    "pcm_alaw",
    "pcm_f32be",
    "pcm_f32le",
    "pcm_f64be",
    "pcm_f64le",
    "pcm_mulaw",
    "pcm_s16be",
    "pcm_s16le",
    "pcm_s24be",
    "pcm_s24le",
    "pcm_s32be",
    "pcm_s32le",
    "pcm_u8",
}

DEFAULT_SIZE_LIMIT_BYTES = 2_000_000_000
DEFAULT_TARGET_BYTES = 1_900_000_000
DEFAULT_MAX_SEGMENT_DURATION_SECONDS = 4 * 60 * 60
DEFAULT_SILENCE_NOISE = "-35dB"
DEFAULT_SILENCE_MIN_DURATION_SECONDS = 2.0
HARD_SPLIT_EPSILON_SECONDS = 0.001
DURATION_TOLERANCE_SECONDS = 2.0
BITRATE_SAFETY_MARGIN = 0.92
OPUS_MAX_BITRATE_BPS = 510_000
OPUS_MIN_REASONABLE_BITRATE_BPS = 16_000
SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<value>[0-9]+(?:\.[0-9]+)?)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(?P<value>[0-9]+(?:\.[0-9]+)?)")


class MediaShrinkerError(RuntimeError):
    """Raised when a media file cannot be processed safely."""


@dataclass(frozen=True)
class MediaProbe:
    """Relevant media properties discovered by ffprobe."""

    duration_seconds: float
    size_bytes: int
    audio_codec: str | None
    audio_bit_rate: int | None
    has_video: bool
    format_name: str


@dataclass(frozen=True)
class ConversionPlan:
    """A concrete ffmpeg conversion plan for one source file."""

    strategy: str
    input_path: Path
    output_path: Path
    ffmpeg_args: list[str]
    audio_bitrate_bps: int | None = None

    def command(
        self,
        *,
        ffmpeg_path: str = "ffmpeg",
        input_path: Path | None = None,
        output_path: Path | None = None,
        overwrite: bool = True,
    ) -> list[str]:
        """Return an executable ffmpeg command with optional path overrides."""

        args = list(self.ffmpeg_args)
        if input_path is not None:
            try:
                input_index = args.index("-i") + 1
            except ValueError as exc:
                raise MediaShrinkerError(
                    "ffmpeg argument template is missing '-i'"
                ) from exc
            args[input_index] = str(input_path.resolve())
        if output_path is not None:
            args[-1] = str(output_path.resolve())

        if overwrite:
            args = ["-y" if arg == "-n" else arg for arg in args]
        else:
            args = ["-n" if arg == "-y" else arg for arg in args]
        return [ffmpeg_path, *args]


@dataclass(frozen=True)
class ConversionResult:
    """Outcome for one processed source file."""

    source_path: Path
    output_path: Path | None
    status: str
    original_size_bytes: int
    output_size_bytes: int | None = None
    strategy: str | None = None
    message: str | None = None
    segment_index: int | None = None
    segment_count: int | None = None
    start_seconds: float | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class SilenceInterval:
    """A detected silence interval that can be used as a split boundary."""

    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class MediaSegment:
    """A source time window that will produce one output file."""

    index: int
    start_seconds: float
    duration_seconds: float
    total_segments: int


def find_candidates(
    root: Path,
    *,
    size_limit_bytes: int = DEFAULT_SIZE_LIMIT_BYTES,
    include_under_limit: bool = True,
    exclude_paths: Iterable[Path] = (),
    exclude_dir_prefixes: Iterable[str] = (),
) -> list[tuple[Path, int]]:
    """Return supported media files under root selected for conversion.

    The returned paths are absolute when root is absolute and are ordered by
    their relative path for repeatable batch runs.
    """

    root = Path(root)
    excluded = tuple(Path(item).resolve() for item in exclude_paths)
    excluded_prefixes = tuple(prefix.casefold() for prefix in exclude_dir_prefixes)
    candidates: list[tuple[Path, int]] = []

    excluded_exact_strs = tuple(str(p) for p in excluded)
    excluded_prefix_strs = tuple(s + os.sep for s in excluded_exact_strs)
    excluded_exact_set = frozenset(excluded_exact_strs)

    for dirpath_str, dirnames, filenames in os.walk(str(root)):
        try:
            resolved_dir_str = os.path.realpath(dirpath_str)
        except OSError:
            continue

        if excluded_exact_strs:
            if resolved_dir_str in excluded_exact_set or resolved_dir_str.startswith(
                excluded_prefix_strs
            ):
                dirnames[:] = []
                continue

        # Prune excluded directories
        valid_dirs = []
        for d in dirnames:
            if d.casefold().startswith(excluded_prefixes):
                continue

            d_path_str = os.path.join(dirpath_str, d)

            try:
                d_stat = os.lstat(d_path_str)
                is_symlink = stat.S_ISLNK(d_stat.st_mode)
            except OSError:
                continue

            if excluded_exact_strs:
                if not is_symlink:
                    resolved_d_str = os.path.join(resolved_dir_str, d)
                else:
                    try:
                        resolved_d_str = os.path.realpath(d_path_str)
                    except OSError:
                        continue

                if resolved_d_str in excluded_exact_set or resolved_d_str.startswith(
                    excluded_prefix_strs
                ):
                    continue
            valid_dirs.append(d)
        dirnames[:] = valid_dirs

        for f in filenames:
            if not f.lower().endswith(SUPPORTED_EXTS_TUPLE):
                continue

            file_path_str = os.path.join(dirpath_str, f)

            try:
                st = os.lstat(file_path_str)
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    continue
                size = st.st_size
            except OSError:
                continue

            if excluded_exact_strs:
                resolved_file_str = os.path.join(resolved_dir_str, f)
                if (
                    resolved_file_str in excluded_exact_set
                    or resolved_file_str.startswith(excluded_prefix_strs)
                ):
                    continue

            if include_under_limit or size > size_limit_bytes:
                candidates.append((Path(file_path_str), size))

    # Fast path: Pre-compute the root string prefix to avoid slow Path.relative_to() instantiation in the sort loop
    # We add a trailing slash to handle cases where root represents a directory structure.
    root_prefix = root.as_posix()
    if not root_prefix.endswith("/"):
        root_prefix += "/"

    return sorted(
        candidates,
        key=lambda item: item[0].as_posix().removeprefix(root_prefix).casefold(),
    )


def calculate_audio_bitrate(
    duration_seconds: float,
    target_bytes: int,
    source_bitrate_bps: int | None,
    *,
    safety_margin: float = BITRATE_SAFETY_MARGIN,
) -> int:
    """Calculate the highest safe audio bitrate for target_bytes.

    Raises:
        ValueError: If duration or target size is not positive.
        MediaShrinkerError: If fitting the file would require an unusably low bitrate.
    """

    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be positive, got {duration_seconds}")
    if target_bytes <= 0:
        raise ValueError(f"target_bytes must be positive, got {target_bytes}")

    fitting_bitrate = int((target_bytes * 8 * safety_margin) / duration_seconds)
    bitrate = min(fitting_bitrate, OPUS_MAX_BITRATE_BPS)
    if source_bitrate_bps and source_bitrate_bps > 0:
        bitrate = min(bitrate, source_bitrate_bps)
    if bitrate < OPUS_MIN_REASONABLE_BITRATE_BPS:
        raise MediaShrinkerError(
            f"Target size requires {bitrate} bps, below the safe floor of "
            f"{OPUS_MIN_REASONABLE_BITRATE_BPS} bps"
        )
    return bitrate


def build_audio_plan(
    source_path: Path,
    probe: MediaProbe,
    *,
    target_bytes: int,
    output_dir: Path,
    prefer_flac: bool = False,
    ffmpeg_threads: int | None = None,
    segment: MediaSegment | None = None,
) -> ConversionPlan:
    """Build the preferred audio-only conversion plan for source_path."""

    if probe.has_video:
        raise MediaShrinkerError(
            f"{source_path} contains video; this tool is configured for audio preservation"
        )
    if not probe.audio_codec:
        raise MediaShrinkerError(f"{source_path} has no audio stream")

    suffix = ".flac" if prefer_flac or _is_lossless_probe(probe) else ".opus"
    output_path = _planned_output_path(
        _segment_source_path(source_path, segment), output_dir, suffix
    )

    if suffix == ".flac":
        strategy = "flac-lossless" if _is_lossless_probe(probe) else "flac-transcode"
        args = [
            "-nostdin",
            "-hide_banner",
            "-y",
        ]
        args.extend(_segment_input_args(segment))
        args.extend(
            [
                "-protocol_whitelist",
                "file,crypto,data",
                "-i",
                str(source_path),
                "-map",
                "0:a:0",
                "-map_metadata",
                "0",
                "-map_chapters",
                "0",
                "-vn",
                "-c:a",
                "flac",
                "-compression_level",
                "12",
                str(output_path),
            ]
        )
        args = _with_ffmpeg_threads(args, ffmpeg_threads)
        return ConversionPlan(
            strategy=strategy,
            input_path=source_path,
            output_path=output_path,
            ffmpeg_args=args,
        )

    return build_opus_plan(
        source_path,
        probe,
        target_bytes=target_bytes,
        output_dir=output_dir,
        ffmpeg_threads=ffmpeg_threads,
        segment=segment,
    )


def build_opus_plan(
    source_path: Path,
    probe: MediaProbe,
    *,
    target_bytes: int,
    output_dir: Path,
    ffmpeg_threads: int | None = None,
    segment: MediaSegment | None = None,
) -> ConversionPlan:
    """Build a high-quality Opus plan that fits the target size."""

    duration_seconds = (
        segment.duration_seconds if segment is not None else probe.duration_seconds
    )
    bitrate = calculate_audio_bitrate(
        duration_seconds, target_bytes, probe.audio_bit_rate
    )
    output_path = _planned_output_path(
        _segment_source_path(source_path, segment), output_dir, ".opus"
    )
    args = [
        "-nostdin",
        "-hide_banner",
        "-y",
    ]
    args.extend(_segment_input_args(segment))
    args.extend(
        [
            "-protocol_whitelist",
            "file,crypto,data",
            "-i",
            str(source_path),
            "-map",
            "0:a:0",
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
            "-vn",
            "-c:a",
            "libopus",
            "-application",
            "audio",
            "-b:a",
            str(bitrate),
            "-vbr",
            "on",
            "-compression_level",
            "10",
            str(output_path),
        ]
    )
    args = _with_ffmpeg_threads(args, ffmpeg_threads)
    return ConversionPlan(
        strategy="opus-bitrate",
        input_path=source_path,
        output_path=output_path,
        ffmpeg_args=args,
        audio_bitrate_bps=bitrate,
    )


def probe_media(
    source_path: Path,
    *,
    ffprobe_path: str = "ffprobe",
    source_size: int | None = None,
) -> MediaProbe:
    """Probe source_path with ffprobe and return normalized media properties."""

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-protocol_whitelist",
        "file,crypto,data",
        "-i",
        str(source_path),
    ]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30.0)
    except subprocess.TimeoutExpired as exc:
        raise MediaShrinkerError(f"ffprobe timed out for {source_path}") from exc
    if completed.returncode != 0:
        raise MediaShrinkerError(
            f"ffprobe failed for {source_path}: {completed.stderr.strip()}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaShrinkerError(
            f"ffprobe returned invalid JSON for {source_path}"
        ) from exc

    return _parse_probe_payload(payload, source_path, source_size=source_size)


def build_silencedetect_command(
    source_path: Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    silence_noise: str = DEFAULT_SILENCE_NOISE,
    silence_min_duration_seconds: float = DEFAULT_SILENCE_MIN_DURATION_SECONDS,
) -> list[str]:
    """Build an ffmpeg command that detects long silence intervals."""

    if not re.match(r"^[+-]?[0-9]+(\.[0-9]+)?(?:dB)?$", silence_noise):
        raise MediaShrinkerError(f"Invalid silence_noise value: {silence_noise}")

    return [
        ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file,crypto,data",
        "-i",
        str(source_path),
        "-af",
        f"silencedetect=noise={silence_noise}:d={_format_seconds(silence_min_duration_seconds)}",
        "-f",
        "null",
        "-",
    ]


def detect_silence_intervals(
    source_path: Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    silence_noise: str = DEFAULT_SILENCE_NOISE,
    silence_min_duration_seconds: float = DEFAULT_SILENCE_MIN_DURATION_SECONDS,
) -> list[SilenceInterval]:
    """Run ffmpeg silencedetect and return paired silence intervals."""

    try:
        completed = subprocess.run(
            build_silencedetect_command(
                source_path,
                ffmpeg_path=ffmpeg_path,
                silence_noise=silence_noise,
                silence_min_duration_seconds=silence_min_duration_seconds,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=180.0,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaShrinkerError(f"silencedetect timed out for {source_path}") from exc
    if completed.returncode != 0:
        raise MediaShrinkerError(
            f"silencedetect failed for {source_path}: {completed.stderr.strip()}"
        )
    return parse_silencedetect_intervals(completed.stderr)


def parse_silencedetect_intervals(stderr: str) -> list[SilenceInterval]:
    """Parse ffmpeg silencedetect stderr into complete silence intervals."""

    intervals: list[SilenceInterval] = []
    current_start: float | None = None
    for line in stderr.splitlines():
        # Fast path: Substring search is much faster than regex.
        # Most lines are ffmpeg progress updates (e.g., 'frame=...')
        if "silence" not in line:
            continue
        start_match = SILENCE_START_RE.search(line)
        if start_match:
            current_start = float(start_match.group("value"))
            continue

        end_match = SILENCE_END_RE.search(line)
        if end_match and current_start is not None:
            end_seconds = float(end_match.group("value"))
            if end_seconds > current_start:
                intervals.append(
                    SilenceInterval(
                        start_seconds=current_start, end_seconds=end_seconds
                    )
                )
            current_start = None
    return intervals


def build_segments(
    *,
    duration_seconds: float,
    max_segment_duration_seconds: float = DEFAULT_MAX_SEGMENT_DURATION_SECONDS,
    silence_intervals: Iterable[SilenceInterval] = (),
) -> list[MediaSegment]:
    """Build source windows that are each shorter than max_segment_duration_seconds.

    Split points prefer the latest safe point inside a detected silence interval
    that fits inside the current four-hour window. If no silence exists in that
    window, a hard split is placed just below the maximum duration.
    """

    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be positive, got {duration_seconds}")
    if max_segment_duration_seconds <= HARD_SPLIT_EPSILON_SECONDS:
        raise ValueError(
            "max_segment_duration_seconds must be greater than "
            f"{HARD_SPLIT_EPSILON_SECONDS}"
        )

    if duration_seconds < max_segment_duration_seconds:
        return [
            MediaSegment(
                index=1,
                start_seconds=0.0,
                duration_seconds=duration_seconds,
                total_segments=1,
            )
        ]

    sorted_intervals = sorted(silence_intervals, key=lambda item: item.start_seconds)
    split_points: list[float] = []
    segment_start = 0.0
    while duration_seconds - segment_start >= max_segment_duration_seconds:
        window_end = segment_start + max_segment_duration_seconds
        split_point = _choose_silence_split_point(
            segment_start, window_end, sorted_intervals
        )
        if split_point is None:
            split_point = window_end - HARD_SPLIT_EPSILON_SECONDS
        if split_point <= segment_start:
            split_point = min(
                duration_seconds,
                segment_start
                + max_segment_duration_seconds
                - HARD_SPLIT_EPSILON_SECONDS,
            )
        split_points.append(split_point)
        segment_start = split_point

    boundaries = [0.0, *split_points, duration_seconds]
    total_segments = len(boundaries) - 1
    return [
        MediaSegment(
            index=index,
            start_seconds=start,
            duration_seconds=end - start,
            total_segments=total_segments,
        )
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
    ]


def build_icloud_download_command(
    source_path: Path, *, brctl_path: str = "brctl"
) -> list[str]:
    """Build a safe iCloud download command for source_path."""

    return [brctl_path, "download", str(source_path.resolve())]


def download_from_icloud(source_path: Path, *, brctl_path: str = "brctl") -> None:
    """Ask macOS iCloud Drive to materialize source_path before media reads."""

    if not shutil.which(brctl_path):
        raise MediaShrinkerError(
            f"iCloud download requested but '{brctl_path}' was not found"
        )
    try:
        completed = subprocess.run(
            build_icloud_download_command(source_path, brctl_path=brctl_path),
            check=False,
            capture_output=True,
            text=True,
            timeout=300.0,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaShrinkerError(f"iCloud download timed out for {source_path}") from exc
    if completed.returncode != 0:
        raise MediaShrinkerError(
            f"iCloud download failed for {source_path}: {completed.stderr.strip()}"
        )


def choose_worker_count(requested_workers: int, *, cpu_count: int | None = None) -> int:
    """Choose a safe parallel conversion worker count.

    requested_workers <= 0 means automatic: use multiple workers, but leave CPU
    headroom because each ffmpeg process can also use multiple threads.
    """

    if requested_workers > 0:
        return requested_workers
    cores = cpu_count or os.cpu_count() or 1
    return max(1, min(4, cores // 2))


@functools.cache
def _get_setfile_path() -> str | None:
    """Return the path to the SetFile executable, cached for efficiency."""
    return shutil.which("SetFile")


def preserve_file_attributes(
    source: Path, dest: Path, *, setfile_path: str | None = None
) -> None:
    """Best-effort copy of filesystem metadata from source to dest.

    This preserves permissions, atime/mtime with nanosecond precision, extended
    attributes where the OS exposes them, and macOS creation date when SetFile is
    available. Non-critical metadata copy failures are ignored so a completed
    conversion is not lost.
    """

    source = Path(source)
    dest = Path(dest)
    source_stat = source.stat()

    try:
        os.chmod(dest, stat.S_IMODE(source_stat.st_mode) & 0o777)
    except OSError:
        pass

    _copy_extended_attributes(source, dest)

    os.utime(dest, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))

    resolved_setfile = setfile_path if setfile_path is not None else _get_setfile_path()
    if resolved_setfile:
        _copy_macos_creation_time(source_stat, dest, resolved_setfile)
        os.utime(dest, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))


def convert_file(
    source: Path,
    *,
    root: Path,
    output_dir: Path,
    target_bytes: int = DEFAULT_TARGET_BYTES,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    download_icloud: bool = False,
    brctl_path: str = "brctl",
    prefer_flac: bool = False,
    ffmpeg_threads: int | None = None,
    overwrite: bool = False,
    max_segment_duration_seconds: float = DEFAULT_MAX_SEGMENT_DURATION_SECONDS,
    silence_noise: str = DEFAULT_SILENCE_NOISE,
    silence_min_duration_seconds: float = DEFAULT_SILENCE_MIN_DURATION_SECONDS,
    protected_sources: Iterable[Path] = (),
    resolved_protected_sources: frozenset[Path] | None = None,
    original_size: int | None = None,
) -> list[ConversionResult]:
    """Convert one file and return generated segment results without deleting the source."""

    source = Path(source)
    root = Path(root)
    output_dir = Path(output_dir)
    original_size = (
        original_size if original_size is not None else safe_source_size(source)
    )

    rel_source = source.relative_to(root)
    if download_icloud:
        download_from_icloud(source, brctl_path=brctl_path)
    probe = probe_media(source, ffprobe_path=ffprobe_path, source_size=original_size)

    silence_intervals: list[SilenceInterval] = []
    if probe.duration_seconds >= max_segment_duration_seconds:
        silence_intervals = detect_silence_intervals(
            source,
            ffmpeg_path=ffmpeg_path,
            silence_noise=silence_noise,
            silence_min_duration_seconds=silence_min_duration_seconds,
        )

    segments = build_segments(
        duration_seconds=probe.duration_seconds,
        max_segment_duration_seconds=max_segment_duration_seconds,
        silence_intervals=silence_intervals,
    )

    resolved_sources = resolved_protected_sources
    if resolved_sources is None:
        resolved_sources = frozenset(Path(item).resolve() for item in protected_sources)

    return [
        _convert_segment(
            source,
            rel_source=rel_source,
            probe=probe,
            segment=segment,
            output_dir=output_dir,
            target_bytes=target_bytes,
            original_size=original_size,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            prefer_flac=prefer_flac,
            ffmpeg_threads=ffmpeg_threads,
            overwrite=overwrite,
            max_segment_duration_seconds=max_segment_duration_seconds,
            protected_sources=resolved_sources,
        )
        for segment in segments
    ]


def safe_source_size(source: Path) -> int:
    """Return source size for reports without letting stat failures abort a batch."""

    try:
        return Path(source).stat().st_size
    except OSError:
        return 0


def _find_valid_existing_output(
    source: Path,
    *,
    segment_rel_source: Path,
    segment: MediaSegment,
    output_dir: Path,
    target_bytes: int,
    original_size: int,
    ffprobe_path: str,
    max_segment_duration_seconds: float,
    resolved_protected_sources: frozenset[Path],
    existing_suffixes: tuple[str, ...],
) -> ConversionResult | None:
    """Return a ConversionResult if a valid output already exists on disk."""
    existing_output: Path | None = None
    existing_duration: float | None = None
    for suffix in existing_suffixes:
        candidate = _planned_output_path(segment_rel_source, output_dir, suffix)
        if not candidate.exists():
            continue
        _ensure_not_source_path(source, candidate)
        _ensure_not_protected_source_path(resolved_protected_sources, candidate)
        try:
            candidate_size = candidate.stat().st_size
        except OSError:
            continue
        if candidate_size > target_bytes:
            _remove_generated_output(
                source, candidate, protected_sources=resolved_protected_sources
            )
            continue
        candidate_duration = _probe_output_duration(
            candidate, ffprobe_path=ffprobe_path, output_size=candidate_size
        )
        if (
            candidate_duration >= max_segment_duration_seconds
            or not _duration_matches_expected(
                candidate_duration,
                segment.duration_seconds,
            )
        ):
            _remove_generated_output(
                source, candidate, protected_sources=resolved_protected_sources
            )
            continue
        existing_output = candidate
        existing_duration = candidate_duration
        existing_size = candidate_size
        break

    if existing_output is not None:
        return ConversionResult(
            source_path=source,
            output_path=existing_output,
            status="skipped_existing",
            original_size_bytes=original_size,
            output_size_bytes=existing_size,
            strategy="existing",
            message="Existing output is already under target",
            segment_index=segment.index,
            segment_count=segment.total_segments,
            start_seconds=segment.start_seconds,
            duration_seconds=existing_duration,
        )
    return None


def _execute_segment_conversion(
    source: Path,
    *,
    rel_source: Path,
    probe: MediaProbe,
    segment: MediaSegment,
    output_dir: Path,
    target_bytes: int,
    original_size: int,
    ffmpeg_path: str,
    ffprobe_path: str,
    prefer_flac: bool,
    ffmpeg_threads: int | None,
    overwrite: bool,
    max_segment_duration_seconds: float,
    resolved_protected_sources: frozenset[Path],
) -> ConversionResult:
    """Execute the conversion plan(s) for a single segment."""
    plan = build_audio_plan(
        rel_source,
        probe,
        target_bytes=target_bytes,
        output_dir=output_dir,
        prefer_flac=prefer_flac,
        ffmpeg_threads=ffmpeg_threads,
        segment=segment,
    )

    final_output = _resolve_collision(plan.output_path, overwrite=overwrite)
    first_result = _execute_plan(
        plan,
        source,
        final_output,
        ffmpeg_path=ffmpeg_path,
        overwrite=overwrite,
        protected_sources=resolved_protected_sources,
    )
    output_size = first_result.stat().st_size
    if output_size > target_bytes and plan.strategy in {
        "flac-lossless",
        "flac-transcode",
    }:
        _remove_generated_output(
            source, first_result, protected_sources=resolved_protected_sources
        )
        opus_plan = build_opus_plan(
            rel_source,
            probe,
            target_bytes=target_bytes,
            output_dir=output_dir,
            ffmpeg_threads=ffmpeg_threads,
            segment=segment,
        )
        final_output = _resolve_collision(opus_plan.output_path, overwrite=overwrite)
        first_result = _execute_plan(
            opus_plan,
            source,
            final_output,
            ffmpeg_path=ffmpeg_path,
            overwrite=overwrite,
            protected_sources=resolved_protected_sources,
        )
        plan = opus_plan
        output_size = first_result.stat().st_size

    output_duration = _probe_output_duration(
        first_result, ffprobe_path=ffprobe_path, output_size=output_size
    )
    preserve_file_attributes(source, first_result)
    common_fields = {
        "source_path": source,
        "output_path": first_result,
        "original_size_bytes": original_size,
        "output_size_bytes": output_size,
        "strategy": plan.strategy,
        "segment_index": segment.index,
        "segment_count": segment.total_segments,
        "start_seconds": segment.start_seconds,
        "duration_seconds": output_duration,
    }

    if output_size > target_bytes:
        return _discard_invalid_generated_output(
            source,
            first_result,
            common_fields,
            status="too_large",
            message=f"Output remains above target: {output_size} > {target_bytes}",
            protected_sources=resolved_protected_sources,
        )

    if output_duration >= max_segment_duration_seconds:
        return _discard_invalid_generated_output(
            source,
            first_result,
            common_fields,
            status="too_long",
            message=(
                "Output segment duration remains at or above the configured maximum: "
                f"{output_duration} >= {max_segment_duration_seconds}"
            ),
            protected_sources=resolved_protected_sources,
        )

    if not _duration_matches_expected(output_duration, segment.duration_seconds):
        return _discard_invalid_generated_output(
            source,
            first_result,
            common_fields,
            status="duration_mismatch",
            message=(
                "Output segment duration does not match the planned segment: "
                f"{output_duration} vs {segment.duration_seconds}"
            ),
            protected_sources=resolved_protected_sources,
        )

    return ConversionResult(**common_fields, status="converted")


def _convert_segment(
    source: Path,
    *,
    rel_source: Path,
    probe: MediaProbe,
    segment: MediaSegment,
    output_dir: Path,
    target_bytes: int,
    original_size: int,
    ffmpeg_path: str,
    ffprobe_path: str,
    prefer_flac: bool,
    ffmpeg_threads: int | None,
    overwrite: bool,
    max_segment_duration_seconds: float,
    protected_sources: frozenset[Path] = frozenset(),
) -> ConversionResult:
    """Convert one media segment fitting the target size limit."""
    # protected_sources is passed from convert_file where it is already fully resolved.
    # _ensure_not_source_path explicitly checks against the current source independently.
    resolved_protected_sources = protected_sources
    existing_suffixes = (".flac", ".opus")
    segment_rel_source = _segment_source_path(rel_source, segment)
    _remove_invalid_legacy_outputs(
        source,
        rel_source=rel_source,
        probe=probe,
        output_dir=output_dir,
        suffixes=existing_suffixes,
        target_bytes=target_bytes,
        ffprobe_path=ffprobe_path,
        max_segment_duration_seconds=max_segment_duration_seconds,
        protected_sources=resolved_protected_sources,
    )

    existing_result = _find_valid_existing_output(
        source,
        segment_rel_source=segment_rel_source,
        segment=segment,
        output_dir=output_dir,
        target_bytes=target_bytes,
        original_size=original_size,
        ffprobe_path=ffprobe_path,
        max_segment_duration_seconds=max_segment_duration_seconds,
        resolved_protected_sources=resolved_protected_sources,
        existing_suffixes=existing_suffixes,
    )
    if existing_result is not None:
        return existing_result

    return _execute_segment_conversion(
        source,
        rel_source=rel_source,
        probe=probe,
        segment=segment,
        output_dir=output_dir,
        target_bytes=target_bytes,
        original_size=original_size,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        prefer_flac=prefer_flac,
        ffmpeg_threads=ffmpeg_threads,
        overwrite=overwrite,
        max_segment_duration_seconds=max_segment_duration_seconds,
        resolved_protected_sources=resolved_protected_sources,
    )


def _remove_invalid_legacy_outputs(
    source: Path,
    *,
    rel_source: Path,
    probe: MediaProbe,
    output_dir: Path,
    suffixes: Iterable[str],
    target_bytes: int,
    ffprobe_path: str,
    max_segment_duration_seconds: float,
    protected_sources: frozenset[Path],
) -> None:
    """Remove invalid stem-only outputs created by earlier tool versions."""

    for suffix in suffixes:
        legacy_output = output_dir / rel_source.with_suffix(suffix)
        canonical_output = _planned_output_path(rel_source, output_dir, suffix)
        if legacy_output == canonical_output or not legacy_output.exists():
            continue
        _ensure_not_source_path(source, legacy_output)
        _ensure_not_protected_source_path(protected_sources, legacy_output)
        try:
            legacy_size = legacy_output.stat().st_size
        except OSError:
            continue
        if legacy_size > target_bytes:
            _remove_generated_output(
                source, legacy_output, protected_sources=protected_sources
            )
            continue
        legacy_duration = _probe_output_duration(
            legacy_output, ffprobe_path=ffprobe_path, output_size=legacy_size
        )
        if (
            legacy_duration >= max_segment_duration_seconds
            or not _duration_matches_expected(
                legacy_duration,
                probe.duration_seconds,
            )
        ):
            _remove_generated_output(
                source, legacy_output, protected_sources=protected_sources
            )


def write_report(results: Iterable[ConversionResult], report_path: Path) -> None:
    """Write a machine-readable JSON conversion report."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "source_path": str(result.source_path),
            "output_path": str(result.output_path) if result.output_path else None,
            "status": result.status,
            "strategy": result.strategy,
            "original_size_bytes": result.original_size_bytes,
            "output_size_bytes": result.output_size_bytes,
            "segment_index": result.segment_index,
            "segment_count": result.segment_count,
            "start_seconds": result.start_seconds,
            "duration_seconds": result.duration_seconds,
            "message": result.message,
        }
        for result in results
    ]
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "root", nargs="?", default=".", type=Path, help="Folder to scan"
    )
    parser.add_argument(
        "--size-limit-bytes",
        type=int,
        default=DEFAULT_SIZE_LIMIT_BYTES,
        help="Convert files larger than this size in bytes",
    )
    parser.add_argument(
        "--target-bytes",
        type=int,
        default=DEFAULT_TARGET_BYTES,
        help="Target size in bytes for converted files",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=float,
        default=DEFAULT_MAX_SEGMENT_DURATION_SECONDS,
        help="Maximum duration in seconds per output segment",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("under_2gb"),
        help="Directory to save converted files",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("under_2gb/conversion_report.json"),
        help="Path to save the JSON conversion report",
    )
    parser.add_argument(
        "--ffmpeg", default="ffmpeg", help="Path to the ffmpeg executable"
    )
    parser.add_argument(
        "--ffprobe", default="ffprobe", help="Path to the ffprobe executable"
    )
    parser.add_argument("--brctl", default="brctl", help="Path to the brctl executable")
    parser.add_argument(
        "--download-icloud",
        action="store_true",
        help="Run 'brctl download' before reading each file",
    )
    parser.set_defaults(include_under_limit=True)
    parser.add_argument(
        "--include-under-limit",
        dest="include_under_limit",
        action="store_true",
        help="Also convert supported media files at or below the size limit. This is the default.",
    )
    parser.add_argument(
        "--over-limit-only",
        dest="include_under_limit",
        action="store_false",
        help="Only convert files above --size-limit-bytes.",
    )
    parser.add_argument(
        "--exclude-dir-prefix",
        action="append",
        default=[],
        help="Skip directories whose name starts with this prefix. Can be repeated.",
    )
    parser.add_argument(
        "--flac-all",
        action="store_true",
        help="Prefer FLAC for every audio-only source, including lossy input",
    )
    parser.add_argument(
        "--workers", type=int, default=0, help="Parallel ffmpeg jobs. 0 = auto"
    )
    parser.add_argument(
        "--ffmpeg-threads",
        type=int,
        default=0,
        help="Pass -threads to ffmpeg. 0 = ffmpeg auto",
    )
    parser.add_argument(
        "--silence-noise",
        default=DEFAULT_SILENCE_NOISE,
        help="ffmpeg silencedetect noise threshold",
    )
    parser.add_argument(
        "--silence-min-duration-seconds",
        type=float,
        default=DEFAULT_SILENCE_MIN_DURATION_SECONDS,
        help="Minimum silence duration used as a preferred split boundary",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually convert files. Omit for a dry run.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting generated output paths",
    )
    return parser.parse_args(argv)


def _execute_conversions(
    candidates: list[tuple[Path, int]],
    args: argparse.Namespace,
    root: Path,
    output_dir: Path,
) -> list[ConversionResult]:
    """Execute conversions in parallel."""
    results: list[ConversionResult] = []
    workers = choose_worker_count(args.workers)
    ffmpeg_threads = args.ffmpeg_threads if args.ffmpeg_threads >= 0 else None

    resolved_candidates = frozenset(Path(item[0]).resolve() for item in candidates)
    protected_sources = [c[0] for c in candidates]

    def process_candidate(candidate_tuple: tuple[Path, int]) -> list[ConversionResult]:
        candidate, size = candidate_tuple
        try:
            return convert_file(
                candidate,
                root=root,
                output_dir=output_dir,
                target_bytes=args.target_bytes,
                ffmpeg_path=args.ffmpeg,
                ffprobe_path=args.ffprobe,
                download_icloud=args.download_icloud,
                brctl_path=args.brctl,
                prefer_flac=args.flac_all,
                ffmpeg_threads=ffmpeg_threads,
                overwrite=args.overwrite,
                max_segment_duration_seconds=args.max_duration_seconds,
                silence_noise=args.silence_noise,
                silence_min_duration_seconds=args.silence_min_duration_seconds,
                protected_sources=protected_sources,
                resolved_protected_sources=resolved_candidates,
                original_size=size,
            )
        except Exception as exc:  # noqa: BLE001 - batch processing records per-file failures.
            return [
                ConversionResult(
                    source_path=candidate,
                    output_path=None,
                    status="failed",
                    original_size_bytes=safe_source_size(candidate),
                    message=str(exc),
                )
            ]

    print(f"WORKERS\t{workers}\tFFMPEG_THREADS\t{ffmpeg_threads}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_candidate = {
            executor.submit(process_candidate, candidate): candidate
            for candidate in candidates
        }
        for future in as_completed(future_to_candidate):
            candidate_results = future.result()
            results.extend(candidate_results)
            for result in candidate_results:
                print(_format_result(root, result), flush=True)

    return results


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""

    args = parse_args(argv)
    root = args.root.resolve()
    output_dir = (
        args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    )
    report_path = args.report if args.report.is_absolute() else root / args.report

    candidates = find_candidates(
        root,
        size_limit_bytes=args.size_limit_bytes,
        include_under_limit=args.include_under_limit,
        exclude_paths=[output_dir],
        exclude_dir_prefixes=args.exclude_dir_prefix,
    )
    if not args.execute:
        for candidate, size in candidates:
            print(f"DRY-RUN\t{size}\t{candidate.relative_to(root)}")
        print(f"TOTAL_SELECTED={len(candidates)}")
        return 0

    results = _execute_conversions(candidates, args, root, output_dir)

    # Fast path: Pre-compute the root string prefix to avoid slow Path.relative_to() instantiation in the sort loop
    root_prefix = root.as_posix()
    if not root_prefix.endswith("/"):
        root_prefix += "/"

    results.sort(
        key=lambda result: (
            result.source_path.as_posix().removeprefix(root_prefix).casefold()
        )
    )
    write_report(results, report_path)
    failed = [
        result
        for result in results
        if result.status not in {"converted", "skipped_existing"}
    ]
    print(f"REPORT\t{report_path}")
    print(
        f"SUMMARY\tconverted={len(results) - len(failed)}\tfailed_or_too_large={len(failed)}"
    )
    return 1 if failed else 0


def _is_lossless_probe(probe: MediaProbe) -> bool:
    """Return True if the probed codec is considered lossless."""
    return (probe.audio_codec or "").lower() in LOSSLESS_AUDIO_CODECS


def _probe_output_duration(
    output_path: Path, *, ffprobe_path: str, output_size: int | None = None
) -> float:
    """Return the duration of a generated output file."""
    return probe_media(
        output_path, ffprobe_path=ffprobe_path, source_size=output_size
    ).duration_seconds


def _duration_matches_expected(
    actual_seconds: float,
    expected_seconds: float,
    *,
    tolerance_seconds: float = DURATION_TOLERANCE_SECONDS,
) -> bool:
    """Return True if actual duration is close enough to expected duration."""
    return abs(actual_seconds - expected_seconds) <= tolerance_seconds


def _discard_invalid_generated_output(
    source: Path,
    output_path: Path,
    common_fields: dict[str, Any],
    *,
    status: str,
    message: str,
    protected_sources: frozenset[Path] = frozenset(),
) -> ConversionResult:
    """Delete an invalid output and return a failure ConversionResult."""
    _remove_generated_output(source, output_path, protected_sources=protected_sources)
    invalid_fields = dict(common_fields)
    invalid_fields["output_path"] = None
    return ConversionResult(**invalid_fields, status=status, message=message)


def _remove_generated_output(
    source: Path,
    output_path: Path,
    *,
    protected_sources: frozenset[Path] = frozenset(),
) -> None:
    """Safely remove a generated file without touching protected sources."""
    _ensure_not_source_path(source, output_path)
    _ensure_not_protected_source_path(protected_sources, output_path)
    output_path.unlink(missing_ok=True)


def _ensure_not_protected_source_path(
    protected_sources: frozenset[Path], output: Path
) -> None:
    """Raise MediaShrinkerError if output would overwrite a protected source."""
    resolved_output = output.resolve()
    if resolved_output in protected_sources:
        raise MediaShrinkerError(
            f"Refusing to use protected source path as generated output: {output}"
        )


def _choose_silence_split_point(
    segment_start: float,
    window_end: float,
    silence_intervals: Iterable[SilenceInterval],
) -> float | None:
    """Return the latest safe split point inside a silence interval."""
    latest_safe_end = window_end - HARD_SPLIT_EPSILON_SECONDS
    candidates = [
        min(interval.end_seconds, latest_safe_end)
        for interval in silence_intervals
        if interval.end_seconds > segment_start + HARD_SPLIT_EPSILON_SECONDS
        and interval.start_seconds < latest_safe_end
    ]
    candidates = [
        candidate for candidate in candidates if segment_start < candidate < window_end
    ]
    return max(candidates) if candidates else None


def _segment_source_path(source_path: Path, segment: MediaSegment | None) -> Path:
    """Return the output filename for a specific segment part."""
    if segment is None or segment.total_segments <= 1:
        return source_path
    return source_path.with_name(f"{source_path.name}.part{segment.index:04d}")


def _segment_input_args(segment: MediaSegment | None) -> list[str]:
    """Return ffmpeg -ss and -t arguments for a segment if applicable."""
    if segment is None or segment.total_segments <= 1:
        return []
    return [
        "-ss",
        _format_seconds(segment.start_seconds),
        "-t",
        _format_seconds(segment.duration_seconds),
    ]


def _format_seconds(value: float) -> str:
    """Format a second value for ffmpeg arguments with three decimals."""
    truncated = int(value * 1000) / 1000
    return f"{truncated:.3f}".rstrip("0").rstrip(".") or "0"


def _planned_output_path(source_path: Path, output_dir: Path, suffix: str) -> Path:
    """Return the canonical output path for a source and suffix."""
    relative_source = (
        Path(source_path.name) if source_path.is_absolute() else source_path
    )
    return output_dir / relative_source.with_name(f"{relative_source.name}{suffix}")


def _with_ffmpeg_threads(args: list[str], ffmpeg_threads: int | None) -> list[str]:
    """Insert ffmpeg -threads before the output path when requested."""

    if ffmpeg_threads is None:
        return args
    return [*args[:-1], "-threads", str(ffmpeg_threads), args[-1]]


def _parse_probe_payload(
    payload: dict[str, Any],
    source_path: Path,
    source_size: int | None = None,
) -> MediaProbe:
    """Parse raw ffprobe JSON payload into a MediaProbe object."""
    streams = payload.get("streams", [])
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    if audio_stream is None:
        raise MediaShrinkerError(f"{source_path} has no audio stream")

    format_section = payload.get("format", {})
    duration = _first_float(
        audio_stream.get("duration"), format_section.get("duration")
    )
    if duration <= 0:
        raise MediaShrinkerError(f"{source_path} has no usable duration")

    parsed_size = _first_int(format_section.get("size"))
    if parsed_size is None:
        parsed_size = (
            source_size if source_size is not None else source_path.stat().st_size
        )

    audio_bit_rate = _first_int(
        audio_stream.get("bit_rate"), format_section.get("bit_rate")
    )
    return MediaProbe(
        duration_seconds=duration,
        size_bytes=parsed_size,
        audio_codec=audio_stream.get("codec_name"),
        audio_bit_rate=audio_bit_rate,
        has_video=any(stream.get("codec_type") == "video" for stream in streams),
        format_name=str(format_section.get("format_name", "")),
    )


def _first_float(*values: Any) -> float:
    """Return the first non-null float from a list of values."""
    for value in values:
        if value is None or value == "N/A":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _first_int(*values: Any) -> int | None:
    """Return the first non-null int from a list of values."""
    for value in values:
        if value is None or value == "N/A":
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _execute_plan(
    plan: ConversionPlan,
    source: Path,
    final_output: Path,
    *,
    ffmpeg_path: str,
    overwrite: bool,
    protected_sources: frozenset[Path] = frozenset(),
) -> Path:
    """Execute a conversion plan using ffmpeg."""
    _ensure_not_protected_source_path(protected_sources, final_output)
    _ensure_not_source_path(source, final_output)
    final_output.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_output_str = tempfile.mkstemp(
        suffix=final_output.suffix,
        prefix=f".{final_output.stem}.",
        dir=final_output.parent,
    )
    os.close(fd)
    temp_output = Path(temp_output_str)

    _ensure_not_protected_source_path(protected_sources, temp_output)
    _ensure_not_source_path(source, temp_output)

    try:
        command = plan.command(
            ffmpeg_path=ffmpeg_path,
            input_path=source,
            output_path=temp_output,
            overwrite=True,
        )
        try:
            completed = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=1800.0
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaShrinkerError(f"ffmpeg conversion timed out for {source}") from exc
        except FileNotFoundError as exc:
            raise MediaShrinkerError(f"ffmpeg not found: {ffmpeg_path}") from exc

        if completed.returncode != 0:
            raise MediaShrinkerError(
                f"ffmpeg failed for {source}: {completed.stderr.strip()}"
            )

        if final_output.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {final_output}")

        temp_output.replace(final_output)
    finally:
        temp_output.unlink(missing_ok=True)

    return final_output


def _ensure_not_source_path(source: Path, output: Path) -> None:
    """Reject generated paths that would overwrite or delete the source file."""

    if source.resolve() == output.resolve():
        raise MediaShrinkerError(
            f"Refusing to use source path as generated output: {output}"
        )


def _resolve_collision(path: Path, *, overwrite: bool) -> Path:
    """Return path or a numbered variant if path already exists."""
    if overwrite or not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find free output path for {path}")


def _copy_extended_attributes(source: Path, dest: Path) -> None:
    """Copy extended attributes from source to dest if supported by OS."""
    if not all(hasattr(os, attr) for attr in ("listxattr", "getxattr", "setxattr")):
        return

    try:
        names = os.listxattr(source)  # type: ignore[attr-defined]
    except OSError:
        return

    for name in names:
        try:
            value = os.getxattr(source, name)  # type: ignore[attr-defined]
            os.setxattr(dest, name, value)  # type: ignore[attr-defined]
        except OSError:
            continue


def _copy_macos_creation_time(
    source_stat: os.stat_result, dest: Path, setfile_path: str
) -> None:
    """Copy macOS creation time using SetFile if available."""
    birthtime = getattr(source_stat, "st_birthtime", None)
    if birthtime is None:
        return
    creation_date = datetime.fromtimestamp(float(birthtime)).strftime(
        "%m/%d/%Y %H:%M:%S"
    )
    try:
        subprocess.run(
            [setfile_path, "-d", creation_date, str(dest.resolve())],
            check=False,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
    except subprocess.TimeoutExpired:
        pass


def _format_result(root: Path, result: ConversionResult) -> str:
    """Format a single conversion result for CLI output."""
    source = _display_path(root, result.source_path)
    output = (
        ""
        if result.output_path is None
        else str(_display_path(root, result.output_path))
    )
    return (
        f"{result.status.upper()}\t{result.strategy or ''}\t"
        f"{result.original_size_bytes}\t{result.output_size_bytes or ''}\t{source}\t{output}\t{result.message or ''}"
    )


def _display_path(root: Path, path: Path) -> Path:
    """Return path relative to root if possible, otherwise absolute."""
    return path.relative_to(root) if path.is_relative_to(root) else path


if __name__ == "__main__":
    sys.exit(main())
