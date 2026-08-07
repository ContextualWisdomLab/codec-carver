#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 5 ]; then
  echo "usage: $0 <role> <model> <timeout-seconds> <prompt-file> <title>" >&2
  exit 64
fi

role="$1"
model="$2"
timeout_seconds="$3"
prompt_file="$4"
title="$5"
role_dir=".github/opencode"
role_prompt="$role_dir/${role}.md"

case "$role" in
  commercial-auditor|commercial-builder) ;;
  *) echo "unsupported OpenCode role: $role" >&2; exit 64 ;;
esac
if ! [[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "timeout must be a positive integer" >&2
  exit 64
fi
for required in "$prompt_file" "$role_prompt" "$role_dir/commercial-readiness.jsonc"; do
  test -f "$required" || { echo "missing required file: $required" >&2; exit 66; }
done

config_backup="$RUNNER_TEMP/opencode-jsonc.${role}.backup"
prompt_backup="$RUNNER_TEMP/${role}.backup"
had_config=0
had_prompt=0
if [ -f opencode.jsonc ]; then cp opencode.jsonc "$config_backup"; had_config=1; fi
if [ -f "${role}.md" ]; then cp "${role}.md" "$prompt_backup"; had_prompt=1; fi
restore_role_files() {
  if [ "$had_config" = "1" ]; then cp "$config_backup" opencode.jsonc; else rm -f opencode.jsonc; fi
  if [ "$had_prompt" = "1" ]; then cp "$prompt_backup" "${role}.md"; else rm -f "${role}.md"; fi
}
trap restore_role_files EXIT
cp "$role_dir/commercial-readiness.jsonc" opencode.jsonc
cp "$role_prompt" "${role}.md"
timeout "$timeout_seconds" opencode run "$(cat "$prompt_file")" \
  --pure \
  --agent "$role" \
  --model "$model" \
  --title "$title"
restore_role_files
trap - EXIT
