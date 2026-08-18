#!/usr/bin/env bash
# Idempotent Cloud Agent setup for codec-carver.
set -euo pipefail

# Pin to the repository root so pip/cargo always act on the checked-out tree,
# regardless of the caller's working directory.
cd "$(dirname "$0")/.."

# ffmpeg AND ffprobe are required at runtime for probing and conversion. The
# default Cloud Agent base image already ships them; install only if either is
# missing.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends ffmpeg
fi

# The pinned toolchain (rust-toolchain.toml) uses profile = minimal, which omits
# rustfmt. Add it fail-closed: `cargo fmt --check` is a CI gate, so a missing
# formatter must break setup rather than silently ship format drift.
# `cargo build` below auto-installs the pinned toolchain first if needed.
cargo build --release --manifest-path rust-core/Cargo.toml
rustup component add rustfmt

# Python dependencies follow CI's supply-chain contract: every runtime and
# dev/test dependency comes from the hash-locked sets, never resolved from the
# index. The package itself is then installed editable with --no-deps so no
# unpinned dependency is ever pulled.
python3 -m pip install --user --disable-pip-version-check --require-hashes -r requirements-lock.txt
python3 -m pip install --user --disable-pip-version-check --require-hashes -r fuzz/requirements-dev.txt
# Build isolation is left on (unlike CI's --no-index --no-build-isolation): this
# base image ships packaging 24.0, but setuptools 83 needs packaging>=24.2, so
# an isolated build environment supplies a compatible, version-pinned backend
# (from pyproject's build-system.requires) without touching runtime deps.
python3 -m pip install --user --disable-pip-version-check --no-deps -e .

# Expose pip --user console scripts (codec-carver, codec-carver-library, ...) in
# non-login shells too. Login shells already pick up ~/.local/bin via ~/.profile.
if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  printf '\nif [ -d "$HOME/.local/bin" ]; then PATH="$HOME/.local/bin:$PATH"; fi\n' >> "$HOME/.bashrc"
fi
