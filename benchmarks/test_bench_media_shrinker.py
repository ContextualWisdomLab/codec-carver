"""Benchmarks for the CPU-bound planning and parsing paths of ``media_shrinker``.

Every function exercised here is pure (no ffmpeg/ffprobe subprocess and no
filesystem access), so the results are deterministic under CodSpeed's CPU
simulation instrument.
"""

from pathlib import Path

import pytest

import media_shrinker
from media_shrinker import MediaProbe, SilenceInterval

# A 12-hour recording with a detected silence roughly every 45 seconds.
_LONG_DURATION_SECONDS = 12 * 60 * 60.0
_SILENCE_EVERY_SECONDS = 45.0


def _silencedetect_stderr(count: int) -> str:
    """Build a realistic ffmpeg ``silencedetect`` stderr log with ``count`` pairs."""
    lines = [
        "ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers",
        "Input #0, wav, from 'recording.wav':",
        "  Duration: 12:00:00.00, bitrate: 1411 kb/s",
    ]
    for index in range(count):
        start = index * _SILENCE_EVERY_SECONDS + 12.25
        end = start + 2.5 + (index % 7) * 0.125
        lines.append(
            f"[silencedetect @ 0x55d0c8a1b2c0] silence_start: {start:.6f}"
        )
        lines.append(
            f"size=N/A time={start:.2f} bitrate=N/A speed=512x"
        )
        lines.append(
            f"[silencedetect @ 0x55d0c8a1b2c0] silence_end: {end:.6f} | "
            f"silence_duration: {end - start:.6f}"
        )
    return "\n".join(lines)


def _silence_intervals(count: int) -> list[SilenceInterval]:
    """Return ``count`` evenly spread, unsorted silence intervals."""
    intervals = [
        SilenceInterval(
            start_seconds=index * _SILENCE_EVERY_SECONDS + 12.25,
            end_seconds=index * _SILENCE_EVERY_SECONDS + 15.0,
        )
        for index in range(count)
    ]
    # Reverse so build_segments has to sort its input like real callers do.
    intervals.reverse()
    return intervals


_SILENCE_LOG_SMALL = _silencedetect_stderr(100)
_SILENCE_LOG_LARGE = _silencedetect_stderr(5_000)
_INTERVALS = _silence_intervals(int(_LONG_DURATION_SECONDS // _SILENCE_EVERY_SECONDS))


@pytest.mark.parametrize(
    "stderr",
    [
        pytest.param(_SILENCE_LOG_SMALL, id="100_silences"),
        pytest.param(_SILENCE_LOG_LARGE, id="5000_silences"),
    ],
)
def test_parse_silencedetect_intervals(benchmark, stderr):
    """Parse ffmpeg silencedetect stderr into silence intervals."""
    intervals = benchmark(media_shrinker.parse_silencedetect_intervals, stderr)
    assert intervals


@pytest.mark.parametrize(
    "max_segment_seconds",
    [
        pytest.param(4 * 60 * 60.0, id="4h_windows"),
        pytest.param(10 * 60.0, id="10min_windows"),
    ],
)
def test_build_segments_with_silences(benchmark, max_segment_seconds):
    """Plan split windows for a 12h recording using detected silences."""
    segments = benchmark(
        media_shrinker.build_segments,
        duration_seconds=_LONG_DURATION_SECONDS,
        max_segment_duration_seconds=max_segment_seconds,
        silence_intervals=_INTERVALS,
    )
    assert len(segments) > 1


def test_build_segments_hard_splits(benchmark):
    """Plan split windows when no silence is available (hard splits only)."""
    segments = benchmark(
        media_shrinker.build_segments,
        duration_seconds=_LONG_DURATION_SECONDS,
        max_segment_duration_seconds=60.0,
        silence_intervals=(),
    )
    assert len(segments) > 1


_PROBE_PAYLOAD = {
    "streams": [
        {"codec_type": "video", "codec_name": "mjpeg"},
        *({"codec_type": "data", "codec_name": "bin_data"} for _ in range(30)),
        {
            "codec_type": "audio",
            "codec_name": "pcm_s24le",
            "duration": "43200.000000",
            "bit_rate": "2304000",
        },
        {"codec_type": "audio", "codec_name": "aac", "duration": "43200.0"},
    ],
    "format": {
        "duration": "43200.000000",
        "size": "12441600000",
        "bit_rate": "2304000",
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
    },
}


def test_parse_probe_payload(benchmark):
    """Parse a multi-stream ffprobe JSON payload into a MediaProbe."""

    def parse_many():
        source = Path("recording.m4a")
        for _ in range(200):
            media_shrinker._parse_probe_payload(_PROBE_PAYLOAD, source)

    benchmark(parse_many)


_LOSSLESS_PROBE = MediaProbe(
    duration_seconds=_LONG_DURATION_SECONDS,
    size_bytes=12_441_600_000,
    audio_codec="pcm_s24le",
    audio_bit_rate=2_304_000,
    has_video=False,
    format_name="wav",
)
_LOSSY_PROBE = MediaProbe(
    duration_seconds=_LONG_DURATION_SECONDS,
    size_bytes=4_000_000_000,
    audio_codec="aac",
    audio_bit_rate=256_000,
    has_video=False,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)
_TAGS = {
    "title": "Weekly research meeting",
    "artist": "Codec Carver",
    "album": "Archive",
    "date": "2026-01-01",
    "comment": "carved from long recording",
}


@pytest.mark.parametrize(
    ("probe", "output_format"),
    [
        pytest.param(_LOSSLESS_PROBE, "auto", id="flac_auto"),
        pytest.param(_LOSSY_PROBE, "auto", id="opus_auto"),
        pytest.param(_LOSSY_PROBE, "aac", id="aac"),
        pytest.param(_LOSSY_PROBE, "mp3", id="mp3"),
    ],
)
def test_build_audio_plan_for_segments(benchmark, probe, output_format):
    """Build ffmpeg conversion plans for every segment of a long recording."""
    segments = media_shrinker.build_segments(
        duration_seconds=probe.duration_seconds,
        max_segment_duration_seconds=30 * 60.0,
        silence_intervals=_INTERVALS,
    )
    source = Path("/archive/recordings/meeting.wav")
    output_dir = Path("/archive/under_2gb")

    def build_all():
        return [
            media_shrinker.build_audio_plan(
                source,
                probe,
                target_bytes=media_shrinker.DEFAULT_SIZE_LIMIT_BYTES,
                output_dir=output_dir,
                ffmpeg_threads=4,
                segment=segment,
                tags=_TAGS,
                normalize=True,
                output_format=output_format,
            )
            for segment in segments
        ]

    plans = benchmark(build_all)
    assert len(plans) == len(segments)


def test_calculate_audio_bitrate(benchmark):
    """Compute target-fitting bitrates across a range of durations."""

    def compute_many():
        total = 0
        for minutes in range(10, 1_450, 3):
            total += media_shrinker.calculate_audio_bitrate(
                minutes * 60.0,
                media_shrinker.DEFAULT_SIZE_LIMIT_BYTES,
                320_000,
            )
        return total

    assert benchmark(compute_many) > 0
