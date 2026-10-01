# `httpx2` dependency security RCA

Status: Proposed until exact-current-head hosted Checks and independent review
complete.

## Failure evidence

`codec-carver#651@21950a764a6e59483b1792199360bb20bb46e542`
failed Security Scan run `36608104327`, job `109720869095`. The exact-head
Trivy SARIF contained four fixable findings at `requirements.txt:7`:

- CVE-2026-84382 (HIGH)
- CVE-2026-84378 (MEDIUM)
- CVE-2026-84379 (MEDIUM)
- CVE-2026-84380 (MEDIUM)

All four findings originate from `httpx2==2.5.0`, which was declared only in
the development dependency set and had no source import or runtime caller.

## Canonical repair

The dependency owner is `codec-carver#668`. It removes `httpx2`, `httpcore2`,
and `truststore` from source and generated manifests while retaining the
supported `httpx` dependency. A repository contract scans
`requirements.txt`, `requirements-lock.txt`, and `pyproject.toml` so a future
manifest edit cannot restore the obsolete dependency family silently.

The contract was first run against #651 and failed for all three manifests.
It passes against #668 after the existing owner repair.

## Consumer integration

#651 preserves its original performance delta and ordinary-merges
`#668@4f2b97e7fb30f5602bf0f697077fea4ed3ffddff`. The only overlapping source
hunk was the shared `intersection_update` optimization; conflict resolution
keeps #651's explanatory comment and #668's additional score-loop change.
Neither lineage is discarded or rewritten.

The resulting exact head must rerun Security, CI, SAST, fuzz, and CodeQL and
remain unmerged while any required result is skipped, pending, queued, or
failed.
