#!/usr/bin/env bash
# Per-boot reconciliation: ensure the Rust backend binary exists after a fresh
# checkout (install is not re-run when a pod boots from a prebuilt environment).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x rust-core/target/release/codec-carver-core ]; then
  cargo build --release --manifest-path rust-core/Cargo.toml
fi
