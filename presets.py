"""Scenario presets for :mod:`media_shrinker`.

A *preset* bundles sensible defaults for a common recording scenario so that a
non-expert user gets good results with a single ``--preset`` flag instead of
tuning a handful of low-level ffmpeg knobs by hand.

Every value here is expressed as an override over the *real* command-line
options exposed by :func:`media_shrinker.parse_args`; the keys below are the
argparse ``dest`` names (``target_bytes``, ``flac_all``, ``silence_noise``,
``silence_min_duration_seconds``, ``max_duration_seconds``).  A preset only
lists the options it wants to change -- anything it omits falls back to the
tool's built-in default, and any option the user sets explicitly on the command
line always wins over the preset (see :func:`apply_preset`).

Preset design rationale (grounded in the tool's real defaults:
``silence_noise="-35dB"``, ``silence_min_duration_seconds=2.0``,
``flac_all=False``, ``target_bytes=1_900_000_000``):

* ``voice`` -- speech, lectures, meetings, voice memos.  Keeps the default Opus
  path (``flac_all`` stays ``False``) and trims aggressively: a higher (less
  negative) silence threshold and a short minimum silence duration make brief
  pauses count as split boundaries.
* ``podcast`` -- conversational, edited audio.  Balanced Opus settings that sit
  between ``voice`` and ``music``: the default silence threshold with a moderate
  minimum silence duration.
* ``music`` -- lossless-leaning audio where quiet passages matter.  Enables
  ``flac_all`` and uses a gentler (more negative) silence threshold with a
  longer minimum duration so soft musical passages are never mistaken for
  silence.
* ``archive`` -- maximum-fidelity long-term storage.  Enables ``flac_all``,
  raises ``target_bytes`` closer to the 2 GB size limit for more headroom, and
  uses the most conservative silence detection so almost nothing is treated as a
  split boundary.
"""

from __future__ import annotations

import argparse

# Sentinel marking a preset-tunable option that the user did NOT set on the
# command line.  ``parse_args`` pre-seeds the namespace with this value so that
# argparse leaves it untouched unless the user explicitly passes the flag; that
# lets :func:`apply_preset` distinguish "user did not set" from "user set it to
# the default value".
_UNSET = object()

# argparse ``dest`` names that a preset is allowed to override.  Kept in sync
# with the corresponding ``add_argument`` calls in ``media_shrinker.parse_args``.
PRESET_TUNABLE_DESTS: tuple[str, ...] = (
    "target_bytes",
    "max_duration_seconds",
    "flac_all",
    "silence_noise",
    "silence_min_duration_seconds",
)

# Mapping of preset name -> {dest: override_value}.  Only the options a preset
# intends to change are listed; omitted options fall back to the real default.
PRESETS: dict[str, dict[str, object]] = {
    "voice": {
        "flac_all": False,
        "silence_noise": "-30dB",
        "silence_min_duration_seconds": 0.5,
    },
    "podcast": {
        "flac_all": False,
        "silence_noise": "-35dB",
        "silence_min_duration_seconds": 1.0,
    },
    "music": {
        "flac_all": True,
        "silence_noise": "-45dB",
        "silence_min_duration_seconds": 3.0,
    },
    "archive": {
        "flac_all": True,
        "target_bytes": 1_950_000_000,
        "silence_noise": "-50dB",
        "silence_min_duration_seconds": 4.0,
    },
}


def preset_names() -> tuple[str, ...]:
    """Return the available preset names, in definition order."""
    return tuple(PRESETS)


def apply_preset(
    args: argparse.Namespace, real_defaults: dict[str, object]
) -> argparse.Namespace:
    """Resolve preset-tunable options on ``args`` in place and return it.

    ``args`` is expected to carry :data:`_UNSET` for every dest in
    :data:`PRESET_TUNABLE_DESTS` that the user did not pass explicitly (see the
    sentinel seeding in ``media_shrinker.parse_args``).  ``real_defaults`` maps
    each of those dests to the tool's built-in default value.

    Precedence, highest first:

    1. A value the user set explicitly on the command line (not :data:`_UNSET`).
    2. A value supplied by ``args.preset`` (when a preset is selected).
    3. The tool's built-in default from ``real_defaults``.

    With no preset selected this is byte-identical to plain argparse defaults:
    every unset dest simply receives its real default.
    """
    overrides = PRESETS[args.preset] if getattr(args, "preset", None) else {}
    for dest, default_value in real_defaults.items():
        if getattr(args, dest, _UNSET) is _UNSET:
            setattr(args, dest, overrides.get(dest, default_value))
    return args
