#!/usr/bin/env python3
"""Optional per-project config file support for media_shrinker.

Users who run the same shrink workflow repeatedly can store their flag set in
a ``.codec-carver.json`` file at the scan root (or the current working
directory) instead of re-typing long command lines. Values from the config
file are applied only where the user did not pass an explicit CLI flag, so
the command line always wins and a missing config file leaves behavior
byte-identical to a plain invocation.

Format choice: JSON instead of TOML. The stdlib TOML parser (``tomllib``)
only exists on Python 3.11+, while this project also supports Python 3.10.
``json`` is available on every supported interpreter, needs no third-party
dependency, and covers the flat key/value shape this file requires.

Example ``.codec-carver.json``::

    {
        "target_bytes": 500000000,
        "flac_all": true,
        "workers": 2,
        "exclude_dir_prefix": ["split_", "tmp_"]
    }

Keys map 1:1 to ``media_shrinker`` CLI options with dashes replaced by
underscores (``--target-bytes`` becomes ``target_bytes``). The ``root``
positional and the ``--execute`` flag are deliberately not configurable:
``root`` is where the config file itself is discovered, and ``--execute``
must stay an explicit per-run decision so a config file can never silently
turn a dry run into a real conversion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_FILENAME = ".codec-carver.json"


class ConfigFileError(ValueError):
    """Raised when a config file exists but cannot be used safely."""


def _bool_value(key: str, value: Any) -> bool:
    """Return value if it is a JSON boolean, else raise ConfigFileError."""

    if isinstance(value, bool):
        return value
    raise ConfigFileError(_type_error_message(key, "a boolean (true/false)", value))


def _int_value(key: str, value: Any) -> int:
    """Return value if it is a JSON integer, else raise ConfigFileError."""

    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ConfigFileError(_type_error_message(key, "an integer", value))


def _float_value(key: str, value: Any) -> float:
    """Return value as float if it is a JSON number, else raise ConfigFileError."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ConfigFileError(_type_error_message(key, "a number", value))


def _str_value(key: str, value: Any) -> str:
    """Return value if it is a JSON string, else raise ConfigFileError."""

    if isinstance(value, str):
        return value
    raise ConfigFileError(_type_error_message(key, "a string", value))


def _path_value(key: str, value: Any) -> Path:
    """Return value converted to a Path if it is a JSON string."""

    return Path(_str_value(key, value))


def _str_list_value(key: str, value: Any) -> list[str]:
    """Return value if it is a JSON array of strings, else raise ConfigFileError."""

    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ConfigFileError(_type_error_message(key, "an array of strings", value))


def _type_error_message(key: str, expected: str, value: Any) -> str:
    """Build a consistent type-mismatch error message for one config key."""

    return (
        f"Config key '{key}' expects {expected}, "
        f"got {type(value).__name__}: {value!r}"
    )


#: Allowlisted config keys mapped to their validating converter. Each key is a
#: real ``media_shrinker.parse_args`` argparse dest so validated values can be
#: assigned onto the parsed namespace unchanged.
CONFIG_SCHEMA = {
    "size_limit_bytes": _int_value,
    "target_bytes": _int_value,
    "max_duration_seconds": _float_value,
    "output_dir": _path_value,
    "report": _path_value,
    "ffmpeg": _str_value,
    "ffprobe": _str_value,
    "brctl": _str_value,
    "download_icloud": _bool_value,
    "include_under_limit": _bool_value,
    "exclude_dir_prefix": _str_list_value,
    "flac_all": _bool_value,
    "workers": _int_value,
    "ffmpeg_threads": _int_value,
    "silence_noise": _str_value,
    "silence_min_duration_seconds": _float_value,
    "overwrite": _bool_value,
}


def find_config_path(root: Path) -> Path | None:
    """Return the config file path for a run, or None when no file exists.

    The scan root is checked first so per-library configs travel with the
    media they describe; the current working directory is the fallback for
    users who keep one config next to where they launch the tool.
    """

    for base in (Path(root), Path.cwd()):
        candidate = base / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def validate_config(raw: dict[str, Any], *, source: Path) -> dict[str, Any]:
    """Validate raw config data against CONFIG_SCHEMA and convert values.

    Raises:
        ConfigFileError: If any key is unknown or any value has the wrong type.
    """

    unknown = sorted(set(raw) - set(CONFIG_SCHEMA))
    if unknown:
        raise ConfigFileError(
            f"Unknown config key(s) in {source}: {', '.join(unknown)}. "
            f"Valid keys: {', '.join(sorted(CONFIG_SCHEMA))}"
        )
    return {key: CONFIG_SCHEMA[key](key, value) for key, value in raw.items()}


def load_config(root: Path) -> dict[str, Any]:
    """Load and validate the ``.codec-carver.json`` config for a scan root.

    Looks for the file in ``root`` first, then in the current working
    directory. Returns an empty dict when no config file exists, so callers
    can treat "no config" and "empty config" identically.

    Raises:
        ConfigFileError: If the file exists but is unreadable, is not valid
            JSON, is not a JSON object, contains unknown keys, or contains
            values of the wrong type.
    """

    path = find_config_path(root)
    if path is None:
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigFileError(f"Could not read config file {path}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigFileError(f"Malformed JSON in config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigFileError(
            f"Config file {path} must contain a JSON object at the top level, "
            f"got {type(raw).__name__}"
        )

    return validate_config(raw, source=path)
