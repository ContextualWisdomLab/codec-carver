#!/usr/bin/env python3
"""Atheris fuzz harness for ``media_shrinker._parse_probe_payload``.

``_parse_probe_payload`` turns a raw ``ffprobe -print_format json`` payload
into a :class:`media_shrinker.MediaProbe`. The payload originates from an
external subprocess parsing an untrusted media file, so its shape and field
types are attacker-influenceable. This harness synthesises JSON-compatible
payloads (the only value types ffprobe can emit) with fuzzed field types and
asserts the parser either returns a valid ``MediaProbe`` or raises the
project's own ``MediaShrinkerError`` — never an unhandled ``KeyError`` /
``TypeError`` / ``ValueError``.

Run locally (Python 3.8 - 3.12)::

    python fuzz/fuzz_parse_probe_payload.py -atheris_runs=200000 fuzz/corpus/parse_probe_payload
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media_shrinker  # noqa: E402

_SOURCE = Path("fuzz_probe_source.bin")
# Values ffprobe realistically emits for numeric-ish fields.
_SCALARS = (None, "N/A", "", "0", "1234.5", "-1", "1e9", "nan", "inf", 0, 1500, 3.14)
_CODEC_TYPES = (None, "audio", "video", "subtitle", "data", "")
_CODEC_NAMES = (None, "flac", "opus", "aac", "pcm_s16le", "mp3", "")


def _pick(fdp, options):
    """Return a deterministic choice from ``options`` driven by fuzzer bytes."""
    if not options:
        return None
    return options[fdp.ConsumeIntInRange(0, len(options) - 1)]


def _build_payload(fdp) -> dict:
    """Assemble a JSON-shaped ffprobe payload from fuzzer-controlled bytes."""
    streams = []
    for _ in range(fdp.ConsumeIntInRange(0, 4)):
        streams.append(
            {
                "codec_type": _pick(fdp, _CODEC_TYPES),
                "codec_name": _pick(fdp, _CODEC_NAMES),
                "duration": _pick(fdp, _SCALARS),
                "bit_rate": _pick(fdp, _SCALARS),
            }
        )
    payload = {
        "streams": streams,
        "format": {
            "duration": _pick(fdp, _SCALARS),
            "size": _pick(fdp, _SCALARS),
            "bit_rate": _pick(fdp, _SCALARS),
            "format_name": _pick(fdp, (None, "wav", "mov,mp4,m4a", "flac", "")),
        },
    }
    return payload


def check_invariants(payload: dict, source_size) -> None:
    """Assert the parser returns a valid probe or a domain-specific error.

    Any exception other than ``MediaShrinkerError`` is a defect.
    """
    try:
        probe = media_shrinker._parse_probe_payload(
            payload, _SOURCE, source_size=source_size
        )
    except media_shrinker.MediaShrinkerError:
        return
    assert isinstance(probe, media_shrinker.MediaProbe)
    assert probe.duration_seconds > 0
    assert isinstance(probe.size_bytes, int)
    assert probe.audio_bit_rate is None or isinstance(probe.audio_bit_rate, int)
    assert isinstance(probe.has_video, bool)
    assert isinstance(probe.format_name, str)


def test_one_input(data: bytes) -> None:
    """Build a payload from fuzzer bytes and run the invariant check."""
    import atheris

    fdp = atheris.FuzzedDataProvider(data)
    # Always supply a concrete size: the ``source_path.stat()`` fallback used
    # when both are absent is filesystem behaviour, not payload parsing.
    source_size = _pick(fdp, (0, 1, 4096, 2_000_000_000, 5_000_000_000))
    payload = _build_payload(fdp)
    check_invariants(payload, source_size)


def main() -> None:
    """Entry point that wires the harness into libFuzzer via Atheris."""
    import atheris

    atheris.instrument_all()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
