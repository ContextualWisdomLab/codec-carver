# Codec Carver product–technical gap baseline

Status: current for the required-input/browser-listener slice on PR #540. The protected branch and current PR head remain the authority for release and merge decisions.

## Product boundary and invariant

Codec Carver owns the upload experience and the server-side media conversion boundary. The browser should report required-field errors before submission without inventing a different business rule from the server.

For the single-file and batch forms, clearing a required file or target-size input must leave both visible text and semantic invalid state. The shared contract is `This field is required.`, `setCustomValidity(...)`, and `aria-invalid="true"`; returning to a valid value must first remove stale required-error styling/state. File and target-size paths should remain symmetric unless the underlying product rule differs.

The batch controls must exist in the parsed document before the inline script binds listeners to them. Binding `batch_preset_buttons_container` while the batch form is still below the executing script causes a null dereference and can abort the rest of the upload interaction code.

## Decision record

Problem: protected `main` silently clears required-input feedback when file or target-size controls are emptied. Its inline script also appears before the batch form while immediately dereferencing batch controls.

Selected repair: keep one existing visual error class, set text plus native/custom validity plus `aria-invalid`, clear stale class/state before revalidation, and place both forms before the inline listener-binding script.

Rejected alternatives:

- Rely only on browser submission blocking. Rejected because an automatically detected missing input should also be identified/described to the user before or at the error state.
- Signal failure by color alone. Rejected because the visible message and semantic invalid state carry information independently of color.
- Guard every missing batch element with optional/null checks while leaving the script before its own required DOM. Rejected because those controls are part of this page's invariant; correct document order is the simpler causal repair.
- Duplicate per-PR CSS or inline error colors. Rejected because the existing `required-star` state is sufficient and avoids another presentation policy.

## Verification and traceability

`tests/test_empty_target_validation.py` locks the single/batch target-size contract. `tests/test_empty_file_validation.py` locks the equivalent file-input contract and verifies that the batch form exists before listener binding. These source-level tests do not substitute for current-head real-browser evidence.

W3C WCAG 2.2 Success Criterion 3.3.1 requires automatically detected input errors to identify the item and describe the error in text; 3.3.2 requires labels or instructions when content requires user input. W3C's current design guidance likewise recommends easily identifiable feedback rather than color-only indication.

World Wide Web Consortium. (2024). *Web Content Accessibility Guidelines (WCAG) 2.2*. https://www.w3.org/TR/WCAG22/

World Wide Web Consortium, Web Accessibility Initiative. (2026). *Designing for web accessibility: Tips for getting started*. https://www.w3.org/WAI/tips/designing/

## Buyer-visible gaps

This material-UI slice is not complete until current-head browser automation exercises single and batch clearing/re-entry, native form submission blocking, drag/drop interaction, live-region/error announcement, focus behavior, and mobile/intermediate/desktop layouts with screenshots or equivalent inspectable artifacts. Static source assertions are necessary regression evidence, not browser acceptance.

Keep release claims separate from this slice. An unchanged protected generation still needs the then-required CI/security/review gates plus immutable release, SBOM/provenance, reproducibility and rollback evidence.
