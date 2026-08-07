#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${OPENCODE_VERSION:?OPENCODE_VERSION is required}"
: "${OPENCODE_SHA256:?OPENCODE_SHA256 is required}"

archive="$RUNNER_TEMP/opencode-linux-x64.tar.gz"
install_dir="$HOME/.opencode/bin"
mkdir -p "$install_dir"
curl --fail --show-error --silent --location \
  --retry 4 --retry-all-errors \
  --output "$archive" \
  "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-x64.tar.gz"
printf '%s  %s\n' "$OPENCODE_SHA256" "$archive" | sha256sum --check --strict
tar -xzf "$archive" -C "$RUNNER_TEMP"
install -m 0755 "$RUNNER_TEMP/opencode" "$install_dir/opencode"
echo "$install_dir" >>"$GITHUB_PATH"
