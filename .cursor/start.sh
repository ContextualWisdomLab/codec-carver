#!/usr/bin/env bash
# Per-boot reconciliation. install is not re-run when a pod boots from a
# prebuilt environment, so anything that must exist on every boot lives here.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1) Ensure the Rust backend binary exists (a fresh checkout wipes rust-core/target).
if [ ! -x rust-core/target/release/codec-carver-core ]; then
  cargo build --release --manifest-path rust-core/Cargo.toml
fi

# 2) Start the FastAPI SaaS web service (saas_web:app) if it is not already up.
# Backgrounded so `start` returns promptly; the guard keeps it a single instance
# and works on every boot mode (just-in-time or prebuilt build/snapshot).
# Logs: /tmp/codec-carver-web.log. Use `python3 -m uvicorn` so it is PATH-independent.
if ! curl -sf -o /dev/null http://127.0.0.1:8000/ 2>/dev/null; then
  nohup python3 -m uvicorn saas_web:app --host 0.0.0.0 --port 8000 \
    > /tmp/codec-carver-web.log 2>&1 &
fi
