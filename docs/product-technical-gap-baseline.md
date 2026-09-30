# Product technical gap baseline

Status: Proposed  
Predecessor pull request: [#665](https://github.com/ContextualWisdomLab/codec-carver/pull/665)  
Historical predecessor regression head: `4b5a5e7901974ff05d39e4f83c4b175fa9eaa541`  
Live predecessor remediation head: `4deca7399cab4c9d633916d31c5631f60fb7f4a5`  
Last audited successor product/evidence head: `62705d2828f6d222245f228bf12d47b871a9561a`  
Successor DOM contract head: `253b4c2b7dc80171ae14fa41b497bfe39feaa692`

## Goal and ownership

codec-carver is the canonical writer for media upload, conversion, and download
interaction semantics. The browser presentation selects files and reports
progress; it does not replace conversion-job or filesystem domain truth.

## Root cause and repair

The predecessor preserved the single/batch shared copy-cursor implementation but
a concurrent writer removed its regression test, CHANGELOG entry, and acceptance
baseline. This successor starts from the historical regression head, preserves
the product JavaScript, and restores those three evidence files. A later
ahead-only commit returned the generated `.jules/palette.md` note to its base
blob because it is not a product or contract requirement. The contract binds
both drop zones, the drag event set, the `DataTransfer` guard,
`dropEffect = "copy"`, and default-event prevention to the generated HTML.

## Context map and security order

- codec-carver owns the upload UI and its interaction contract.
- [#570](https://github.com/ContextualWisdomLab/codec-carver/pull/570) is the
  canonical dependency predecessor, but current head
  `e1c6f0b8cb4976fd65bd32fececea7b94adca811` has a zero-file diff and cannot
  remove the vulnerable `httpx2` family.
- [#639](https://github.com/ContextualWisdomLab/codec-carver/pull/639) at
  `da2ff6f58900bedffb111778bac7eb122b15676e` is the verified successor that
  preserves the dependency cleanup together with the FFmpeg protocol boundary.
- The UI successor must not copy the dependency delta. Integrate #639 through
  the protected branch, then non-force restack and rerun all exact-head checks.

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
| Security | At `62705d2828f6d222245f228bf12d47b871a9561a`, `trivy-fs` failed on inherited `httpx2==2.5.0` with CVE-2026-84382/84378/84379/84380 | FAIL | Integrate #639, restack, and run a fresh exact-head scan |

Skipped jobs, prior-head runs, and status-only review markers are not positive
evidence. This work remains Draft while any applicable row is FAIL or lacks
exact-head review.
