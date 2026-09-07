#!/usr/bin/env bash
# Per-boot reconciliation. install is not re-run when a pod boots from a
# prebuilt environment, so anything that must exist on every boot lives here.
# `start` must reach a clear ready-or-fail state: a green exit with a dead
# uvicorn leaves the published :8000 port pointing at nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="${HOME}/.local/bin:${PATH}"

WEB_HEALTH_URL="${CODEC_CARVER_WEB_HEALTH_URL:-http://127.0.0.1:8000/health}"
WEB_READY_ATTEMPTS="${CODEC_CARVER_WEB_READY_ATTEMPTS:-40}"
WEB_LOG="${CODEC_CARVER_WEB_LOG:-/tmp/codec-carver-web.log}"

# 1) Ensure the Rust backend binary exists (a fresh checkout wipes rust-core/target).
if [ ! -x rust-core/target/release/codec-carver-core ]; then
  cargo build --release --manifest-path rust-core/Cargo.toml
fi

_web_is_ready() {
  curl -sf -o /dev/null "${WEB_HEALTH_URL}"
}

# 2) Start the FastAPI SaaS web service (saas_web:app) if it is not already up.
# Backgrounded so `start` returns after readiness; the probe keeps it a single
# instance on every boot mode (just-in-time or prebuilt build/snapshot).
if _web_is_ready; then
  exit 0
fi

nohup python3 -m uvicorn saas_web:app --host 0.0.0.0 --port 8000 \
  > "${WEB_LOG}" 2>&1 &
web_pid=$!

attempt=0
while [ "${attempt}" -lt "${WEB_READY_ATTEMPTS}" ]; do
  if _web_is_ready; then
    exit 0
  fi
  if ! kill -0 "${web_pid}" 2>/dev/null; then
    echo "uvicorn exited before becoming ready; see ${WEB_LOG}" >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 0.25
done

echo "uvicorn did not become ready after ${WEB_READY_ATTEMPTS} probes; see ${WEB_LOG}" >&2
exit 1
