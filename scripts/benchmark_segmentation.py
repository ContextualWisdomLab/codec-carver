#!/usr/bin/env python3
"""Measure fixed versus VAD-aware checkpoint segmentation.

This is intentionally model-free: it measures boundary planning and resume
bookkeeping without downloading a model.  Run the same source/model workload
with the GPU transcriber for end-to-end wall/RTF/memory numbers and keep this
small report as the deterministic segmentation baseline.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
import json
import math
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_library


def _measure_planner(
    planner: Callable[[], object], duration_seconds: float
) -> tuple[object, dict[str, float | int | str]]:
    """Measure one model-free segmentation planner, not model inference."""

    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = planner()
    finally:
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return result, {
        "scope": "segmentation_planning_only",
        "wall_seconds": round(elapsed, 6),
        "peak_python_bytes": peak,
        "rtf_segmentation_only": round(elapsed / duration_seconds, 9),
    }


def _same_boundary(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-6)


def _boundary_anomaly_count(ranges: object, duration_seconds: float) -> int:
    """Count malformed, discontinuous, duplicated, or missing boundaries."""

    if not isinstance(ranges, list) or not ranges:
        return 1
    anomalies = 0
    previous_end: float | None = None
    internal_boundaries: list[float] = []
    for index, pair in enumerate(ranges):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            anomalies += 1
            previous_end = None
            continue
        try:
            start, end = float(pair[0]), float(pair[1])
        except (TypeError, ValueError):
            anomalies += 1
            previous_end = None
            continue
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            anomalies += 1
        if previous_end is not None and not _same_boundary(start, previous_end):
            anomalies += 1
        if index < len(ranges) - 1:
            internal_boundaries.append(end)
        previous_end = end
    first = ranges[0]
    last = ranges[-1]
    if isinstance(first, (list, tuple)) and len(first) == 2:
        try:
            if not _same_boundary(float(first[0]), 0.0):
                anomalies += 1
        except (TypeError, ValueError):
            anomalies += 1
    else:
        anomalies += 1
    if isinstance(last, (list, tuple)) and len(last) == 2:
        try:
            if not _same_boundary(float(last[1]), duration_seconds):
                anomalies += 1
        except (TypeError, ValueError):
            anomalies += 1
    else:
        anomalies += 1
    for count in Counter(internal_boundaries).values():
        anomalies += max(0, count - 1)
    return anomalies


def _changed_boundary_count(nominal: list, refined: list) -> int:
    """Compare final internal boundaries, counting a moved cut only once."""

    nominal_boundaries = [float(end) for _, end in nominal[:-1]]
    refined_boundaries = [float(end) for _, end in refined[:-1]]
    common_count = min(len(nominal_boundaries), len(refined_boundaries))
    if len(nominal_boundaries) == len(refined_boundaries):
        return sum(
            not _same_boundary(left, right)
            for left, right in zip(nominal_boundaries, refined_boundaries, strict=True)
        )
    changed = sum(
        not _same_boundary(left, right)
        for left, right in zip(
            nominal_boundaries[:common_count],
            refined_boundaries[:common_count],
            strict=True,
        )
    )
    return changed + abs(len(nominal_boundaries) - len(refined_boundaries))


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
    nominal_result, fixed_measurement = _measure_planner(
        lambda: audio_library.automatic_mlx_chunk_ranges(args.duration_seconds),
        args.duration_seconds,
    )
    nominal = nominal_result
    if not nominal:
        raise SystemExit("duration must exceed the bounded-chunk threshold")
    silences = []
    if args.silence_json:
        silences = json.loads(args.silence_json.read_text(encoding="utf-8"))

    vad_result, vad_measurement = _measure_planner(
        lambda: audio_library.refine_checkpoint_ranges_at_silence(
            nominal,
            silences,
            search_seconds=args.search_seconds,
            min_silence_seconds=args.min_silence_seconds,
        ),
        args.duration_seconds,
    )
    vad_ranges, shifts = vad_result
    changed = _changed_boundary_count(nominal, vad_ranges)
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
            "duplicate_or_missing_boundary_count": _boundary_anomaly_count(
                vad_ranges, args.duration_seconds
            ),
            "fixed_boundary_anomaly_count": _boundary_anomaly_count(
                nominal, args.duration_seconds
            ),
            "resume_prefix_cost": len(vad_ranges),
        },
        "measurement": {
            "scope": "model_free_segmentation_planning_only",
            "fixed_nominal": fixed_measurement,
            "vad_refinement": vad_measurement,
            "timestamp_diff": "requires_same-model-GPU-run",
            "speaker_continuity_diff": "requires_same-model-GPU-run",
            "text_diff": "requires_same-model-GPU-run",
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
