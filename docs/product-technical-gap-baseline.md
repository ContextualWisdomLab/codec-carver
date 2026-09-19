# Product Technical Gap Baseline

Status: Proposed  
Canonical owner: `ContextualWisdomLab/codec-carver`  
Tracked change: [PR #595](https://github.com/ContextualWisdomLab/codec-carver/pull/595)

## Goal / PRD

When a user types or selects a target byte count, the single-file and batch forms must expose the same exact selection truth. A preset is selected only when the current value is a positive safe integer equal to that preset's byte count.

## TRD

- Parse the complete input with `Number`; never truncate with `parseInt`.
- Require `Number.isSafeInteger(inputByteCount) && inputByteCount > 0`.
- Derive `aria-pressed` from the validated exact value for both forms.
- Empty, fractional, non-finite, negative, and zero values select no preset.
- Backend validation remains authoritative for submitted domain values.

## Context Map

```text
Browser form (presentation)
  -> exact byte-count validation
  -> POST /shrink or /shrink-batch (application boundary)
  -> existing media shrinking domain
```

Presentation state does not replace the submitted target-byte domain value.

## UML interaction

```text
User -> number input: type or choose value
number input -> validator: Number(value)
validator -> preset buttons: exact positive-safe-integer match
validator -> preview/native validity: valid value or recovery message
User -> form CTA: submit
form -> API: target_bytes
```

## ERD

Not applicable: PR #595 changes no persistent entity, relation, column, or migration.

## Gap / Action / Status

| Gap | Evidence | Action | Status |
| --- | --- | --- | --- |
| Manual exact value did not select its preset | Original PR delta removed the `e.isTrusted` gate | Preserve input-method-independent state | Source candidate |
| Fractional value such as `26214400.5` was truncated to `26214400` | Review against head `81d6d745281ab1389bb0f2296bbf40cefab48a3a` | Exact-value production repair `7586a6619f1fe5d25eddbbc77cc69c691e202526` | Source repaired |
| Test only asserted the former generated string | `tests/test_saas_web.py` before `34b7dfad4ca7ccc9e27ac3da11b58a112644dfb7` | Lock both form copies, safe-integer guard, and removed truncation | Contract candidate |
| Current-head real-browser behavior is unproven | No Playwright/Cypress/WebDriver test found on the protected branch | Verify pointer, touch, keyboard, focus, AT, exact `aria-pressed`, invalid recovery, and CTA→API in Chromium/Firefox/WebKit | Pending |
| Responsive and locale evidence is absent | No current-head 320/768/desktop screenshots or ko/en/ja/zh/vi/es/de/fr matrix | Add versioned screenshots and DB-backed localized resource evidence | Pending |
| Performance is unmeasured | No render/interaction median or p95 artifact | Measure realistic input interactions without reduced samples | Pending |

## Exact-head acceptance rule

A source commit or stale approval is not completion. Merge readiness requires all required workflows and an independent approval on the same current PR head, plus current-head browser evidence for the applicable UI rows above. Queued, pending, skipped, or cancelled checks are not GREEN.
