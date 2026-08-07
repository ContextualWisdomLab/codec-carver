#!/usr/bin/env bash
set -euo pipefail

: "${TARGET_FILE:?TARGET_FILE is required}"
: "${BRANCH_NAME:?BRANCH_NAME is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

issue_number="$(jq -r '.number // empty' "$TARGET_FILE")"
issue_title="$(jq -r '.title // "Commercial-readiness improvement"' "$TARGET_FILE")"
if [ -n "$issue_number" ]; then
  pr_title="feat: address #${issue_number} ${issue_title}"
else
  pr_title="feat: close the next buyer-visible product gap"
fi
pr_title="${pr_title:0:240}"
body_file="$RUNNER_TEMP/commercial-readiness-pr.md"
{
  printf '## Outcome\n\nImplements one bounded buyer-visible improvement selected by the hourly commercial-readiness loop.\n\n'
  printf '## Safety contract\n\n'
  printf -- '- NVIDIA NIM OpenCode roles only; no `COPILOT_GITHUB_TOKEN`\n'
  printf -- '- no workflow, governance, credential, dependency, lockfile, or release-file changes\n'
  printf -- '- at most 12 files and 2500 changed lines\n'
  printf -- '- full unit suite, 100%% line/branch coverage for changed production modules, compile checks, and CLI smoke checks\n'
  printf -- '- no self-approval or self-merge; central review/check/merge automation owns the next transition\n\n'
  if [ -n "$issue_number" ]; then printf 'Closes #%s\n' "$issue_number"; fi
} >"$body_file"
gh pr create --repo "$GITHUB_REPOSITORY" --base main --head "$BRANCH_NAME" \
  --title "$pr_title" --body-file "$body_file"
