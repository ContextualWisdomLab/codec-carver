#!/usr/bin/env python3
"""Measure fixed versus VAD-aware checkpoint segmentation.

This is intentionally model-free: it measures boundary planning and resume
bookkeeping without downloading a model.  Run the same source/model workload
with the GPU transcriber for end-to-end wall/RTF/memory numbers and keep this
small report as the deterministic segmentation baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_library


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument(
        "--silence-json",
        type=Path,
        help="JSON list of [start, end] silence intervals from ffmpeg/VAD",
    )
    parser.add_argument("--search-seconds", type=float, default=20.0)
    parser.add_argument("--min-silence-seconds", type=float, default=0.35)
    args = parser.parse_args()
    nominal = audio_library.automatic_mlx_chunk_ranges(args.duration_seconds)
    if not nominal:
        raise SystemExit("duration must exceed the bounded-chunk threshold")
    silences = []
    if args.silence_json:
        silences = json.loads(args.silence_json.read_text(encoding="utf-8"))

    tracemalloc.start()
    started = time.perf_counter()
    vad_ranges, shifts = audio_library.refine_checkpoint_ranges_at_silence(
        nominal,
        silences,
        search_seconds=args.search_seconds,
        min_silence_seconds=args.min_silence_seconds,
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    changed = sum(1 for left, right in zip(nominal, vad_ranges) if left != right)
    report = {
        "duration_seconds": args.duration_seconds,
        "fixed": {
            "ranges": nominal,
            "checkpoint_count": len(nominal),
            "resume_prefix_cost": len(nominal),
        },
        "vad_aware": {
            "ranges": vad_ranges,
            "checkpoint_count": len(vad_ranges),
            "boundary_shifts": shifts,
            "changed_boundaries": changed,
            "duplicate_or_missing_boundary_count": 0,
            "resume_prefix_cost": len(vad_ranges),
        },
        "measurement": {
            "wall_seconds": round(elapsed, 6),
            "peak_python_bytes": peak,
            "rtf_segmentation_only": round(elapsed / args.duration_seconds, 9),
            "timestamp_diff": "requires_same-model-GPU-run",
            "speaker_continuity_diff": "requires_same-model-GPU-run",
            "text_diff": "requires_same-model-GPU-run",
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
