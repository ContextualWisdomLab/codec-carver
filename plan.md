1. The `noema-review` CI check failed with a timeout error in `urllib.request.urlopen` (TimeoutError: timed out after 120s). This is caused by the external CI infrastructure review bot/sidecar failing to complete the LLM generation request within the 120-second timeout.
2. According to the memory `If the \`noema-review\` CI check fails with a \`413 request_too_large\` or \`sidecar preflight failed\` error, this is an external CI infrastructure issue. Do not attempt to fix it; communicate the issue to the user and re-submit the PR without code changes if your task is already complete.`
3. I will run test suites and check test coverage to make sure nothing is broken.
4. I will call `pre_commit_instructions` tool to complete pre commit steps to make sure proper testing, verifications, reviews and reflections are done.
5. I will submit the PR again without code changes.
