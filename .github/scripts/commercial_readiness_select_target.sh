#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

open_pr_count="$(gh pr list --repo "$GITHUB_REPOSITORY" --state open --limit 1 --json number --jq 'length')"
if [ "$open_pr_count" -gt 0 ]; then
  echo "ready=false" >>"$GITHUB_OUTPUT"
  echo "An open pull request already owns the delivery queue."
  exit 0
fi
if [ -z "${NVIDIA_API_KEY:-}" ]; then
  echo "::error::NVIDIA_NIM_API_KEY is required for the OpenCode worker."
  exit 1
fi

target_file="$RUNNER_TEMP/commercial-target.json"
gh issue list \
  --repo "$GITHUB_REPOSITORY" \
  --state open \
  --limit 100 \
  --json number,title,body,url,createdAt,labels \
  | jq 'sort_by(.createdAt) | .[0] // null' >"$target_file"
if [ "$(jq -r 'type' "$target_file")" = "null" ]; then
  jq -n '{kind:"product_gap",number:null,title:"Buyer-visible product-gap discovery",body:"",url:""}' >"$target_file"
  echo "kind=product_gap" >>"$GITHUB_OUTPUT"
  echo "number=" >>"$GITHUB_OUTPUT"
else
  jq '. + {kind:"issue"}' "$target_file" >"${target_file}.next"
  mv "${target_file}.next" "$target_file"
  echo "kind=issue" >>"$GITHUB_OUTPUT"
  echo "number=$(jq -r '.number' "$target_file")" >>"$GITHUB_OUTPUT"
fi
printf 'ready=true\ntarget_file=%s\n' "$target_file" >>"$GITHUB_OUTPUT"
