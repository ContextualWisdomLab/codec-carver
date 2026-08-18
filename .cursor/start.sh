#!/usr/bin/env bash
# Per-boot startup for codec-carver:
#   1. ensure the Rust backend binary exists after a fresh checkout, and
#   2. bring up the FastAPI SaaS web service and BLOCK until it is ready.
# This is ready-or-fail: a worker that never binds or dies during startup makes
# `start` exit non-zero (a failed boot) instead of leaving the published :8000
# port pointing at nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1) Rust backend binary used by the audio-library CLI (a fresh checkout wipes
#    rust-core/target).
if [ ! -x rust-core/target/release/codec-carver-core ]; then
  cargo build --release --manifest-path rust-core/Cargo.toml
fi

# 2) FastAPI SaaS web service on :8000. Idempotent: if it is already serving,
#    there is nothing to do. Every probe is time-bounded so a port that accepts
#    TCP but never answers HTTP cannot hang startup.
readiness_url="http://127.0.0.1:8000/health"
probe() { curl -fsS --connect-timeout 3 --max-time 5 -o /dev/null "$readiness_url" 2>/dev/null; }
if probe; then
  exit 0
fi

# `python3 -m uvicorn` is PATH-independent; logs go to a stable path.
nohup python3 -m uvicorn saas_web:app --host 0.0.0.0 --port 8000 \
  > /tmp/codec-carver-web.log 2>&1 &
web_pid=$!

# Wait for readiness; fail fast if the worker exits or never becomes ready.
for _ in $(seq 1 60); do
  if ! kill -0 "$web_pid" 2>/dev/null; then
    echo "codec-carver web worker (pid $web_pid) exited during startup" >&2
    cat /tmp/codec-carver-web.log >&2 || true
    exit 1
  fi
  if probe; then
    exit 0
  fi
  sleep 1
done

echo "codec-carver web service did not become ready on $readiness_url within 60s" >&2
cat /tmp/codec-carver-web.log >&2 || true
kill "$web_pid" 2>/dev/null || true
exit 1
