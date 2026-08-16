#!/usr/bin/env bash
# Idempotent Cloud Agent setup for codec-carver.
# Runs after each checkout. Always resolve the repository root from this file
# so a cached or non-root working directory cannot pip/cargo the wrong tree.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="${HOME}/.local/bin:${PATH}"

# ffmpeg/ffprobe are required at runtime for probing and conversion.
# The default Cloud Agent base image already ships them; install only if missing.
if ! command -v ffmpeg >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends ffmpeg
fi

# rustfmt backs `cargo fmt` (rust-toolchain.toml pins a minimal profile without it).
# Fail closed: CI and local agents both run `cargo fmt --check`.
if ! command -v rustup >/dev/null 2>&1; then
  echo "rustup is required so rustfmt can be added for cargo fmt checks." >&2
  exit 1
fi
rustup component add rustfmt

# Match CI: hash-locked runtime deps, then the editable tree without
# re-resolving from the index, then unpinned-but-marked dev extras.
python3 -m pip install --user --disable-pip-version-check \
  --require-hashes -r requirements-lock.txt
python3 -m pip install --user --disable-pip-version-check \
  --no-index --no-deps --no-build-isolation -e .
python3 -m pip install --user --disable-pip-version-check \
  -r requirements-dev.txt

# Rust core binary (codec-carver-core) used by the audio-library CLI.
# A fresh checkout wipes rust-core/target, so (re)build it here.
cargo build --release --manifest-path rust-core/Cargo.toml

# Expose pip --user console scripts (codec-carver, codec-carver-library, ...) in
# non-login shells too. Login shells already pick up ~/.local/bin via ~/.profile.
if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  printf '\nif [ -d "$HOME/.local/bin" ]; then PATH="$HOME/.local/bin:$PATH"; fi\n' >> "$HOME/.bashrc"
fi
