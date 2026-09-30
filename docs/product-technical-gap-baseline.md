# Product technical gap baseline

Status: Proposed  
Pull request: [#665](https://github.com/ContextualWisdomLab/codec-carver/pull/665)  
Source implementation head: `2c50126790eeae159031d55a3640c46e30db70bb`  
DOM contract head: `e455876104cfda566b8b4c19f9f0b984475f4a01`

## Goal and ownership

codec-carver is the canonical writer for media upload, conversion, and download
interaction semantics. The browser presentation selects files and reports
progress; it does not replace conversion-job or filesystem domain truth.

## Current repair

The upload surface already provides native file inputs for keyboard and
assistive-technology operation. Pull request #665 adds native operating-system
copy-cursor feedback during `dragenter` and `dragover` for both the single
and batch drop zones. The regression contract at
`e455876104cfda566b8b4c19f9f0b984475f4a01` binds the shared handler,
`DataTransfer` guard, `dropEffect = "copy"`, and default-event prevention to
the real generated HTML.

## Context map and security order

- codec-carver owns the upload UI and its interaction contract.
- [#570](https://github.com/ContextualWisdomLab/codec-carver/pull/570) is the
  canonical dependency owner for removing the unused `httpx2` family.
- [#639](https://github.com/ContextualWisdomLab/codec-carver/pull/639) preserves
  that removal together with the FFmpeg protocol boundary.
- #665 must not copy the dependency delta. Integrate the canonical owner through
  the protected branch, then non-force restack and rerun exact-head checks.

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
| Security | Prior head `2c50126790eeae159031d55a3640c46e30db70bb` failed repo-wide `trivy-fs` on inherited `httpx2==2.5.0` | FAIL | Owner integration, restack, and fresh exact-head scan |

Skipped jobs and status-only review markers are not positive evidence. This PR
remains Draft while any applicable row is FAIL or lacks exact-head review.
