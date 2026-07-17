#!/bin/bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
RUNTIME_DIR="${CODEC_CARVER_GPU_VENV:-$HOME/Library/Caches/codec-carver/venvs/gpu-py312}"
PYTHON_VERSION="${CODEC_CARVER_GPU_PYTHON:-3.12}"
LOCK_FILE="$REPO_ROOT/requirements-macos-mlx-lock.txt"
UV_BIN="${UV_BIN:-}"
XATTR_BIN="$(command -v xattr || true)"
STAT_BIN="$(command -v stat || true)"

usage() {
    printf '%s\n' \
        "Usage: scripts/bootstrap_macos_gpu_runtime.sh [OPTIONS]" \
        "" \
        "Create or refresh a persistent MLX runtime outside iCloud File Provider." \
        "" \
        "Options:" \
        "  --runtime-dir PATH  Direct child of ~/Library/Caches/codec-carver/venvs" \
        "                      (default: .../gpu-py312)" \
        "  --python VERSION    Python version for uv (default: 3.12)" \
        "  -h, --help          Show this help"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

directory_metadata() {
    local value
    value="$("$STAT_BIN" -f '%d:%i:%u:%Lp' -- "$1" 2>/dev/null || true)"
    if [[ "$value" =~ ^[0-9]+:[0-9]+:[0-9]+:[0-7]+$ ]]; then
        printf '%s\n' "$value"
        return 0
    fi
    "$STAT_BIN" -c '%d:%i:%u:%a' -- "$1"
}

secure_directory_identity() {
    local -r path="$1"
    local -r label="$2"
    local metadata device inode owner mode
    metadata="$(directory_metadata "$path")" || fail "$label metadata is unavailable"
    IFS=: read -r device inode owner mode <<< "$metadata"
    [[ "$device" =~ ^[0-9]+$ && "$inode" =~ ^[0-9]+$ ]] || \
        fail "$label identity is malformed"
    [[ "$owner" == "$EUID" ]] || fail "$label is not owned by this user"
    [[ "$mode" =~ ^[0-7]+$ ]] || fail "$label permissions are malformed"
    case "$mode" in
        *[2367][0-7] | *[0-7][2367])
            fail "$label must not be group- or world-writable"
            ;;
    esac
    printf '%s:%s\n' "$device" "$inode"
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
[[ -n "$PYTHON_VERSION" ]] || fail "Python version must not be empty"
[[ -f "$LOCK_FILE" && ! -L "$LOCK_FILE" ]] || \
    fail "hash-locked macOS MLX requirements are missing"
[[ -n "$STAT_BIN" && -x "$STAT_BIN" ]] || fail "stat is required"

HOME_PHYSICAL="$(cd -- "$HOME" && pwd -P)"
TRUSTED_RUNTIME_ROOT="$HOME_PHYSICAL/Library/Caches/codec-carver/venvs"
mkdir -p -- "$TRUSTED_RUNTIME_ROOT"
TRUSTED_RUNTIME_ROOT="$(cd -- "$TRUSTED_RUNTIME_ROOT" && pwd -P)"
case "$TRUSTED_RUNTIME_ROOT/" in
    "$HOME_PHYSICAL/"*) ;;
    *) fail "trusted runtime root escaped the user home directory" ;;
esac
secure_directory_identity "$TRUSTED_RUNTIME_ROOT" "trusted runtime root" >/dev/null

while [[ "$RUNTIME_DIR" != "/" && "$RUNTIME_DIR" == */ ]]; do
    RUNTIME_DIR="${RUNTIME_DIR%/}"
done
[[ "$RUNTIME_DIR" != "/" && "$RUNTIME_DIR" != "$HOME" ]] || \
    fail "runtime path is too broad"
RUNTIME_NAME="$(basename -- "$RUNTIME_DIR")"
RUNTIME_PARENT="$(dirname -- "$RUNTIME_DIR")"
RUNTIME_PARENT="$(cd -- "$RUNTIME_PARENT" && pwd -P)" || \
    fail "runtime parent must already exist"
[[ "$RUNTIME_PARENT" == "$TRUSTED_RUNTIME_ROOT" ]] || \
    fail "runtime must be a direct child of $TRUSTED_RUNTIME_ROOT"
[[ -n "$RUNTIME_NAME" && "$RUNTIME_NAME" != "." && "$RUNTIME_NAME" != ".." ]] || \
    fail "runtime directory name is unsafe"
RUNTIME_DIR="$TRUSTED_RUNTIME_ROOT/$RUNTIME_NAME"

if ! mkdir -- "$RUNTIME_DIR" 2>/dev/null; then
    [[ -d "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] || \
        fail "runtime path must be a real directory"
fi
RUNTIME_DIR="$(cd -- "$RUNTIME_DIR" && pwd -P)"
[[ "$RUNTIME_DIR" != "/" && "$RUNTIME_DIR" != "$HOME_PHYSICAL" ]] || \
    fail "runtime path is too broad after canonicalization"
[[ "$(dirname -- "$RUNTIME_DIR")" == "$TRUSTED_RUNTIME_ROOT" ]] || \
    fail "runtime escaped the trusted cache root"
RUNTIME_ID="$(secure_directory_identity "$RUNTIME_DIR" "runtime directory")"

if [[ -z "$UV_BIN" ]]; then
    UV_BIN="$(command -v uv || true)"
fi
[[ -n "$UV_BIN" && -x "$UV_BIN" ]] || fail "uv is required and must be executable"
[[ "$UV_BIN" == /* ]] || fail "uv path must be absolute"
[[ -n "$XATTR_BIN" && -x "$XATTR_BIN" ]] || fail "xattr is required"

FILE_PROVIDER_PATH="$RUNTIME_DIR"
while [[ "$FILE_PROVIDER_PATH" != "/" ]]; do
    if "$XATTR_BIN" -p com.apple.file-provider-domain-id "$FILE_PROVIDER_PATH" &>/dev/null; then
        fail "runtime must not be inside an iCloud/File Provider directory"
    fi
    FILE_PROVIDER_PATH="$(dirname -- "$FILE_PROVIDER_PATH")"
done

(
    cd -- "$RUNTIME_DIR"
    [[ "$(secure_directory_identity . "runtime directory")" == "$RUNTIME_ID" ]] || \
        fail "runtime directory identity changed before setup"
    if [[ ! -x "./bin/python" ]]; then
        "$UV_BIN" venv . --python "$PYTHON_VERSION"
    fi
    [[ "$(secure_directory_identity . "runtime directory")" == "$RUNTIME_ID" ]] || \
        fail "runtime directory identity changed during environment creation"
    "$UV_BIN" pip install \
        --python "./bin/python" \
        --require-hashes \
        --only-binary :all: \
        --requirements "$LOCK_FILE"
    [[ "$(secure_directory_identity . "runtime directory")" == "$RUNTIME_ID" ]] || \
        fail "runtime directory identity changed during dependency installation"
)

[[ "$(secure_directory_identity "$RUNTIME_DIR" "runtime directory")" == "$RUNTIME_ID" ]] || \
    fail "runtime directory path changed during bootstrap"

printf 'GPU_RUNTIME_READY\t%s\n' "$RUNTIME_DIR/bin/python"
printf 'Run: %q %q ROOT describe\n' "$RUNTIME_DIR/bin/python" "$REPO_ROOT/audio_library.py"
