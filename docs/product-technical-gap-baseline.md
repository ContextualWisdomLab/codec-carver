# Codec Carver product–technical gap baseline

Status: current for the upload-admission slice on PR #546. Source/test evidence immediately before this documentation commit is `1a52c870280254a7da40ecda98902214f32f3a28`; the PR description and hosted checks are the authority for the current descendant SHA.

## Product boundary

Codec Carver owns media carving/transcoding and its upload experience. A browser-provided MIME value is user-agent metadata used for early feedback, not authenticated media truth. Source bytes remain subject to the server/decoder admission path. The UI must not silently create a stricter media contract than the server.

## Current invariant and decision

The upload UI may immediately reject a non-empty `File.type` that is explicitly outside `audio/*` and `video/*`. An empty `File.type` means that the browser has no usable declared MIME evidence, so the client leaves the decision to the bounded server/decoder path. Single-file and batch upload must use the same rule.

Problem: the first client implementation called `startsWith()` unconditionally and therefore rejected an empty `File.type`. That contradicted both the server's existing unknown-MIME behavior and the web-platform contract.

Constraints: retain the `accept` hint, inline error text, `setCustomValidity`, `aria-invalid`, drag/drop behavior and upload-size limits; do not infer authenticated type from filename extensions; do not bypass server/decoder validation.

Alternatives considered:

- Reject empty browser MIME. Rejected because the File API explicitly permits an empty `Blob.type` when the user agent cannot determine a media type.
- Infer type from the filename extension. Rejected because client-side extension/MIME metadata is advisory and can be absent, inaccurate or attacker-controlled.
- Admit every declared type and rely only on the backend. Rejected because an explicit non-media declaration is still useful low-cost UX evidence for early feedback.
- Reject only explicit non-media declarations and pass unknown MIME to the server. Selected because it preserves the server authority while improving the common invalid-selection path.

## Verification state

The deterministic contract test `tests/test_saas_web_client_media_type_contract.py` covers both client predicates and the server's empty-declared-MIME behavior. The causal client predicates live in `saas_web.py`. A concurrent ordinary descendant fixed the predicates but removed the regression; the fleet repair restored the regression instead of treating missing test coverage as completed work.

Hosted exact-head application/security checks remain the acceptance authority. This slice is not complete as material UI until current-head real-browser evidence covers file selection and drag/drop, error announcement/association, keyboard/focus behavior, and mobile/intermediate/desktop layouts. Static HTML assertions do not substitute for that browser evidence.

## Buyer-visible gaps

1. Add current-head browser E2E and screenshots for explicit non-media rejection, unknown-MIME admission, drag/drop, error announcement and focus behavior at representative viewport widths.
2. Preserve backend byte/decoder validation as the media-truth authority; client metadata must never become a security boundary.
3. Keep the wider service gaps from `AGENTS.md` separate from this UI slice, notably migration of runtime API-key secrets from raw environment reads to the repository's credential-registry/KV boundary.
4. Do not claim release readiness until the unchanged protected generation has its then-required CI/security/review gates plus immutable release evidence.

## Traceability

World Wide Web Consortium. (2026, August 23). *File API* (W3C Working Draft). https://www.w3.org/TR/2026/WD-FileAPI-20260823/

WHATWG. (2026). *HTML Standard: File upload state (`type=file`)*. https://html.spec.whatwg.org/multipage/input.html#file-upload-state-(type=file)

The W3C File API states that `Blob.type` is the empty string when the media type cannot be determined. The HTML Standard describes `accept` as a hint and cautions that MIME types and extensions are not authoritative validation of client-supplied data.
