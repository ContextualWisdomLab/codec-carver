#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
RUNTIME_DIR="${CODEC_CARVER_GPU_VENV:-$HOME/Library/Caches/codec-carver/venvs/gpu-py312}"
PYTHON_VERSION="${CODEC_CARVER_GPU_PYTHON:-3.12}"
LOCK_FILE="$REPO_ROOT/requirements-macos-mlx-lock.txt"
UV_BIN="${UV_BIN:-}"
XATTR_BIN="$(command -v xattr || true)"

usage() {
    printf '%s\n' \
        "Usage: scripts/bootstrap_macos_gpu_runtime.sh [OPTIONS]" \
        "" \
        "Create or refresh a persistent MLX runtime outside iCloud File Provider." \
        "" \
        "Options:" \
        "  --runtime-dir PATH  Runtime venv (default: ~/Library/Caches/codec-carver/venvs/gpu-py312)" \
        "  --python VERSION    Python version for uv (default: 3.12)" \
        "  -h, --help          Show this help"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

on_error() {
    local -r line="$1"
    printf 'ERROR: GPU runtime bootstrap failed at line %s.\n' "$line" >&2
}
trap 'on_error "$LINENO"' ERR

while [[ $# -gt 0 ]]; do
    case "$1" in
        --runtime-dir)
            [[ $# -ge 2 ]] || fail "--runtime-dir requires a path"
            RUNTIME_DIR="$2"
            shift 2
            ;;
        --python)
            [[ $# -ge 2 ]] || fail "--python requires a version"
            PYTHON_VERSION="$2"
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

[[ "$(uname -s)" == "Darwin" ]] || fail "this bootstrap supports macOS MLX only"
[[ "$(uname -m)" == "arm64" ]] || fail "this bootstrap supports Apple Silicon arm64 only"
[[ "$RUNTIME_DIR" == /* ]] || fail "runtime path must be absolute"
[[ "$RUNTIME_DIR" != "/" && "$RUNTIME_DIR" != "$HOME" ]] || \
    fail "runtime path is too broad"
[[ -n "$PYTHON_VERSION" ]] || fail "Python version must not be empty"
[[ -f "$LOCK_FILE" && ! -L "$LOCK_FILE" ]] || \
    fail "hash-locked macOS MLX requirements are missing"
case "$RUNTIME_DIR/" in
    "$REPO_ROOT/"*)
        fail "runtime must be outside the repository and its File Provider path"
        ;;
esac

if [[ -z "$UV_BIN" ]]; then
    UV_BIN="$(command -v uv || true)"
fi
[[ -n "$UV_BIN" && -x "$UV_BIN" ]] || fail "uv is required and must be executable"
[[ -n "$XATTR_BIN" && -x "$XATTR_BIN" ]] || fail "xattr is required"

mkdir -p -- "$RUNTIME_DIR"
RUNTIME_DIR="$(cd -- "$RUNTIME_DIR" && pwd -P)"
case "$RUNTIME_DIR/" in
    "$REPO_ROOT/"*)
        fail "runtime must be outside the repository and its File Provider path"
        ;;
esac
FILE_PROVIDER_PATH="$RUNTIME_DIR"
while [[ "$FILE_PROVIDER_PATH" != "/" ]]; do
    if "$XATTR_BIN" -p com.apple.file-provider-domain-id "$FILE_PROVIDER_PATH" &>/dev/null; then
        fail "runtime must not be inside an iCloud/File Provider directory"
    fi
    FILE_PROVIDER_PATH="$(dirname -- "$FILE_PROVIDER_PATH")"
done

if [[ ! -x "$RUNTIME_DIR/bin/python" ]]; then
    "$UV_BIN" venv "$RUNTIME_DIR" --python "$PYTHON_VERSION"
fi
"$UV_BIN" pip install \
    --python "$RUNTIME_DIR/bin/python" \
    --require-hashes \
    --only-binary :all: \
    --requirements "$LOCK_FILE"

printf 'GPU_RUNTIME_READY\t%s\n' "$RUNTIME_DIR/bin/python"
printf 'Run: %q %q ROOT describe\n' "$RUNTIME_DIR/bin/python" "$REPO_ROOT/audio_library.py"
