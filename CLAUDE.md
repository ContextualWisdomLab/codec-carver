# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Codec Carver is a Python CLI for carving long audio recordings into metadata-preserved, size-capped FLAC/Opus files. It converts supported recordings to FLAC or, only when needed to fit under a target size, high-bitrate Opus. Sources are never overwritten or deleted; generated files go to a separate output directory. Sources at or above the duration cap (default four hours) are split at long silence intervals detected via FFmpeg `silencedetect`, with a hard split just under the cap as fallback. Requires Python 3.10+ and `ffmpeg`/`ffprobe` on `PATH`.

## Common commands

```bash
# Install (the CLI core is stdlib-only; extras pull their own deps)
pip install -e .            # CLI core
pip install -e ".[web]"     # + FastAPI upload service
pip install -e ".[mcp]"     # + MCP server
pip install -r requirements-dev.txt   # hypothesis, coverage, atheris (fuzzing)

# Full test suite (unittest, not pytest)
python3 -m unittest discover -s tests -v

# Single test module / single test
python3 -m unittest tests.test_media_shrinker -v
python3 -m unittest tests.test_job_store.TestCreateAndGet.test_create_get_roundtrip

# Compile check (CI runs this on all four modules)
python -m py_compile media_shrinker.py saas_web.py mcp_driver.py job_store.py

# CLI (omit --execute for a dry run that only lists candidates)
codec-carver /path/to/recordings --execute --output-dir under_2gb

# Web service
uvicorn saas_web:app --host 0.0.0.0 --port 8000
docker build -t codec-carver . && docker run -p 8000:8000 codec-carver

# MCP server
python mcp_driver.py

# Fuzzing (Atheris; CPython <= 3.12, not Windows)
pip install --require-hashes -r fuzz/requirements-fuzz.txt
python fuzz/fuzz_parse_silencedetect.py -max_total_time=60 fuzz/corpus/parse_silencedetect
```

CI installs pinned dependencies with `pip install --require-hashes -r requirements-lock.txt` followed by `pip install --no-index --no-deps --no-build-isolation -e .` — new runtime dependencies must land in `requirements-lock.txt` with hashes as well as in `pyproject.toml`.

## Architecture

Four flat top-level modules (declared as `py-modules` in `pyproject.toml`; there is no package directory):

- **`media_shrinker.py`** — the core engine and CLI, deliberately stdlib-only (external work happens in `ffmpeg`/`ffprobe` subprocesses). The console script `codec-carver` maps to `media_shrinker:main`. Pipeline for a batch run: `find_candidates` scans the root (pruned `os.walk`, excludes the output dir and `--exclude-dir-prefix` dirs) → per file, `convert_file` probes with ffprobe (`probe_media` / `_parse_probe_payload`), detects silence and builds a split plan for long sources (`detect_silence_intervals`, `parse_silencedetect_intervals`, `build_segments`) → each segment gets a `ConversionPlan` (`build_audio_plan` prefers FLAC; `build_opus_plan` is the fallback when a FLAC output exceeds the target size) → `_execute_plan` runs ffmpeg and `preserve_file_attributes` restores permissions/timestamps/xattrs best-effort → `write_report` emits a JSON report. `convert_file(source, root=..., output_dir=..., target_bytes=...)` is the programmatic API that the web and MCP layers call.
- **`saas_web.py`** — single-file FastAPI upload UI (the `[web]` extra; what the Docker image serves). Streams one upload into a temp workspace, calls `media_shrinker.convert_file`, and returns the first generated output as a download. Middleware enforces a 5 GiB upload cap and security headers. Processing is synchronous per request.
- **`mcp_driver.py`** — FastMCP server (the `[mcp]` extra) exposing a single `shrink_media` tool that wraps `convert_file`.
- **`job_store.py`** — stdlib-only SQLite (WAL) durable job store intended for async/worker job tracking. It is tested but not yet wired into `saas_web.py`. Callers pass `now` explicitly; the store never calls `datetime.now()` itself.

Supporting directories: `fuzz/` holds Atheris harnesses plus seed corpora for the three untrusted-input parsing surfaces (`parse_silencedetect_intervals`, `_parse_probe_payload`, `build_segments`); the same invariants run as Hypothesis property tests in `tests/test_fuzz_properties.py` so they execute in the normal suite. `docs/papers/` holds the fuzzing survey the harness design references.

## CI gates (.github/workflows)

- `ci.yml` — Python 3.10/3.11/3.12 matrix: hash-pinned install, `py_compile` of all four modules, `python -m unittest discover -s tests -v`, and `codec-carver --help` entry-point verification.
- `fuzz.yml` — Hypothesis property suite on every push/PR, plus Atheris fuzzing per target (90s/target on PRs, 10 min/target nightly). Crash reproducers (`crash-*`, `oom-*`, `timeout-*`) are uploaded as artifacts and are gitignored — never commit them.

## Key conventions

- **Never endanger sources.** The scan's selected sources are protected from deletion/overwrite (`protected_sources` / `_ensure_not_protected_source_path`). Generated names keep the full original filename plus a new suffix (`clip.wav.flac`, `meeting.wav.part0001.flac`) so same-stem inputs cannot collide. Keep `--output-dir` a generated-only directory.
- **Stdlib-only core.** `media_shrinker.py` and `job_store.py` must not grow third-party imports; FastAPI/MCP dependencies belong to the optional `web`/`mcp` extras. Tests guard optional imports with `skipUnless` so the suite passes without extras installed.
- **Docstring coverage is 100%.** `interrogate` is configured with `fail-under = 100` (excluding `scripts`, `tests`, `fuzz`) — every module and function, including private helpers, needs a docstring. `.coveragerc` likewise sets `fail_under = 100` over `media_shrinker`, `saas_web`, and `mcp_driver`.
- **Security posture.** ffmpeg/ffprobe are always invoked with `-nostdin` and `-protocol_whitelist file,crypto,data` (SSRF/LFI hardening); uploaded filenames are sanitized to a safe basename; temp files use `tempfile` APIs, not predictable names; copied permissions are masked to drop setuid/setgid/sticky bits. `.jules/sentinel.md` logs past vulnerabilities and their prevention rules — check it before touching subprocess invocation, temp-file, or metadata-copy code. `.jules/bolt.md` records performance lessons (pre-resolve paths once, prune walks, avoid repeated `stat`).
- **Fuzzing-first for parsers.** Anything that parses ffmpeg/ffprobe output is an untrusted-input surface: parsers must never raise unexpected exception types on arbitrary input (raise `MediaShrinkerError` for invalid payloads). If you change one, update the matching harness in `fuzz/` and its Hypothesis mirror in `tests/test_fuzz_properties.py`.
- **PR merge gates.** `.agents/skills/github-robot-review-gate/SKILL.md` documents this repo's robot-review (CodeRabbit) merge-gate policy and how to diagnose blocked merges — follow it rather than bypassing branch protection.
