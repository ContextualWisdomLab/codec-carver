#!/usr/bin/env bash
# Idempotent Cloud Agent setup for codec-carver.
# Runs from the repository root (/workspace) after each checkout.
set -euo pipefail

# ffmpeg/ffprobe are required at runtime for probing and conversion.
# The default Cloud Agent base image already ships them; install only if missing.
if ! command -v ffmpeg >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends ffmpeg
fi

# rustfmt backs `cargo fmt` (rust-toolchain.toml pins a minimal profile without it).
rustup component add rustfmt >/dev/null 2>&1 || true

# Python package (codec-carver CLI) + web/mcp extras + dev/test deps
# (interrogate, hypothesis, coverage, atheris). Installed to the user site.
python3 -m pip install --user --disable-pip-version-check -e ".[dev,web,mcp]" -r requirements-dev.txt

# Rust core binary (codec-carver-core) used by the audio-library CLI.
# A fresh checkout wipes rust-core/target, so (re)build it here.
cargo build --release --manifest-path rust-core/Cargo.toml

# Expose pip --user console scripts (codec-carver, codec-carver-library, ...) in
# non-login shells too. Login shells already pick up ~/.local/bin via ~/.profile.
if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  printf '\nif [ -d "$HOME/.local/bin" ]; then PATH="$HOME/.local/bin:$PATH"; fi\n' >> "$HOME/.bashrc"
fi
