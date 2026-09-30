# Product technical gap baseline

Status: Proposed  
Predecessor pull request: [#665](https://github.com/ContextualWisdomLab/codec-carver/pull/665)  
Predecessor regression head: `4b5a5e7901974ff05d39e4f83c4b175fa9eaa541`  
Successor DOM contract head: `253b4c2b7dc80171ae14fa41b497bfe39feaa692`

## Goal and ownership

codec-carver is the canonical writer for media upload, conversion, and download
interaction semantics. The browser presentation selects files and reports
progress; it does not replace conversion-job or filesystem domain truth.

## Root cause and repair

The predecessor preserved the single/batch shared copy-cursor implementation but
a concurrent writer removed its regression test, CHANGELOG entry, and acceptance
baseline. This successor starts from that exact predecessor head and restores
the evidence without altering the product JavaScript. The contract binds both
drop zones, the drag event set, the `DataTransfer` guard,
`dropEffect = "copy"`, and default-event prevention to the generated HTML.

## Context map and security order

- codec-carver owns the upload UI and its interaction contract.
- [#570](https://github.com/ContextualWisdomLab/codec-carver/pull/570) is the
  canonical dependency owner for removing the unused `httpx2` family.
- [#639](https://github.com/ContextualWisdomLab/codec-carver/pull/639) preserves
  that removal together with the FFmpeg protocol boundary.
- The UI successor must not copy the dependency delta. Integrate the canonical
  owner through the protected branch, then non-force restack and rerun checks.

## Exact-head acceptance matrix

| Area | Exact evidence | Status | Merge gate |
| --- | --- | --- | --- |
| Determinism | One shared source contract covers both drop zones and the copy effect | Checks pending | Exact-head test and review |
| Domain semantics | Native file inputs remain the authoritative file-selection controls | Source-only PASS | Browser and accessibility-tree confirmation |
| Pointer drag and drop | Shared handler sets copy feedback and clears the visual class on leave/drop | Source-only PASS | Real pointer drag, drop, cancellation, and cleanup evidence |
| Keyboard alternative | Native single and multiple file inputs remain available | Source-only PASS | Complete keyboard flow with visible focus |
| Touch | Native picker exists; touch interaction and target measurements are absent | FAIL | Mobile touch evidence and 44 by 44 CSS-pixel targets |
| Responsive and zoom | No current-head desktop, intermediate, mobile, 200% zoom, or reflow screenshots | FAIL | Capture all required layouts |
| Reduced motion | This delta adds no motion; existing transitions are not current-head browser-verified | PARTIAL | Reduced-motion browser verification |
| Runtime states | Busy and validation states exist; loading, offline, permission, read-only, stale, conflict, and retry coverage is incomplete | FAIL | Applicable Storybook or real-browser state evidence |
| Locales | The upload UI is not proven for ko/en/ja/zh/vi/es/de/fr | FAIL | Versioned screen resources and locale E2E |
| Large data and performance | Limits are 5 GiB and 20 batch files; realistic browser and server latency evidence is absent | FAIL | Measure the documented limits without sample reduction |
| Import, export, and recovery | Upload and file/zip download paths exist; interrupted upload, retry, regeneration, and rollback evidence is absent | FAIL | Recovery and deterministic export evidence |
| Security | The predecessor failed repo-wide `trivy-fs` on inherited `httpx2==2.5.0` | FAIL | Owner integration, restack, and fresh exact-head scan |

Skipped jobs and status-only review markers are not positive evidence. This work
remains Draft while any applicable row is FAIL or lacks exact-head review.
