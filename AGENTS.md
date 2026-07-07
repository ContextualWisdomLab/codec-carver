# AGENTS.md

Cross-agent conventions for **codec-carver** — a Python CLI/FastAPI tool for
carving long recordings into metadata-preserved FLAC/Opus files. These notes
apply to any coding agent (Claude, Codex, Cursor, opencode, …) working in this
repo.

<!-- BEGIN cwl-agent-guidance -->
## Agent guidance (CWL governance)

### Security & review gate
- Every PR runs a central **Security Scan** required gate: `osv-scan` +
  `dependency-review` (diff-scoped) and `trivy-fs` (repo-wide; CRITICAL/HIGH,
  fixable only). It runs on every PR base, **including stacked PRs**.
- A **failing `trivy-fs` is a REAL finding, not a flake.** Read the job log — it
  prints each finding's rule id, severity, and file — or inspect the run's SARIF
  results. Then **remediate**:
  - This repo's dependencies are Python packages declared in `requirements.txt`
    (currently `fastapi`, `uvicorn`, `python-multipart`, `mcp`, `aiofiles`,
    `httpx`). A dependency CVE means bumping/pinning the affected package there.
  - There is **no Dockerfile or k8s manifest** today; if you add one, a trivy
    misconfig finding means fixing that IaC file directly.
  - Only for a genuine false positive, add a narrow, documented
    `.trivyignore` (or `.trivyignore.yaml`) entry — one CVE id with a reason.
- **Do NOT weaken or disable the gate.** A local scan with a stale DB misses
  findings: run `trivy --download-db-only` first, then scan the **merge ref**
  (not just the PR head), e.g. `trivy fs --severity CRITICAL,HIGH --ignore-unfixed .`.
- The org `code_scanning` ruleset is intentionally **CodeQL-only** (multiple
  code-scanning tools can't converge on one PR ref). Gating is by the Security
  Scan **job result**, not the code_scanning rule — **don't add tools to that rule.**

### Code exploration
- There is no `.codegraph/` index in this repo today, so use normal search
  (grep/find) to locate and understand code. If a `.codegraph/` directory is
  ever added at the repo root, prefer CodeGraph first —
  `codegraph explore "<query>"` or the code-review-graph MCP tools — before
  grep/find; it surfaces callers, callees, and impact that text search misses.
<!-- END cwl-agent-guidance -->
