# Codec Carver product–technical gap baseline

Status: Proposed / code-current baseline  
Evidence generation before this document: `d3e153905ae4ece2fa9fd882f722564ffe3b1c8d` on PR #543  
Protected target: `main@47c6fd27de13b0da37a7db64697b869941909351`  
Last reviewed: 2026-09-08

## Product boundary

Codec Carver owns media carving/transcoding, metadata-preserved outputs, long-recording segmentation and the optional web/MCP service boundary used to feed STT and omni-modal pipelines. Byte-heavy library curation is Rust-backed where practical; Python remains the web/orchestration and compatibility boundary described by the repository's current implementation.

The SaaS web service is a separate application boundary around those media operations. Authentication must fail closed before any upload/conversion work is admitted.

## Authentication invariants

- When API-key authentication is configured, every non-root request must present a matching key or receive the ordinary 401 response.
- Malformed, Unicode or otherwise adversarial header values must not escape the authentication middleware as request-time exceptions.
- Secret comparison retains a constant-time primitive and does not reflect configured key material in responses.
- Runtime secrets/config must ultimately be read from the repository-approved credential registry/KV. Raw environment access is bootstrap transport only, not the target runtime architecture.

## Current gap register

| Gap | Buyer/control impact | Current evidence | Acceptance |
| --- | --- | --- | --- |
| Non-ASCII API-key handling | Direct `str` use with `hmac.compare_digest` can raise `TypeError` for non-ASCII input, converting an authentication rejection into a 500-class middleware failure. | PR #543 compares UTF-8 bytes and exercises a non-ASCII header through `require_api_key()`. Current-head CI/fuzz/Security/SAST are terminal GREEN; CodeQL remains pending. | Unchanged exact head gets terminal-success CodeQL and then-live review/thread gates; non-ASCII wrong keys stay on the same 401 contract as other wrong keys. |
| Runtime credential source | `saas_web.py` still reads `CODEC_CARVER_API_KEYS` via the raw environment. `AGENTS.md` explicitly records this as a known architecture deviation and requires migration to a credential registry/KV. | Current production `get_configured_api_keys()` uses `os.environ`. The existing `JobStore` demonstrates a short-lived SQLite/WAL persistence pattern but is not itself a credential store. | Introduce a purpose-built credential registry with encrypted-at-rest secret values, bootstrap/import semantics, rotation/revocation tests and no request-time `os.getenv`/`os.environ` secret reads. Do not silently repurpose the jobs table. |
| Authentication lifecycle | A static comma-separated key list has no first-class key identity, activation/expiry, rotation receipt or audit metadata. | Current middleware treats configured keys as anonymous values. | Credential aggregate defines key identity/status/version, rotation without downtime, revocation, purpose scope and audit evidence; API behavior remains backward-compatible only through an explicit migration contract. |
| Commercial security baseline | This canonical gap document did not exist on the protected branch before PR #543. | Protected-base lookup returned no `docs/product-technical-gap-baseline.md`. | Keep this file code-current with authentication, media pipeline, operability and release evidence rather than treating passing tests as product completion. |

## PR #543 decision record

Problem: a non-ASCII `X-API-Key` can reach Python's `hmac.compare_digest` as `str`; that API rejects non-ASCII strings with `TypeError`, creating a request-time 500 path.

Decision: normalize both compared values to UTF-8 bytes at the comparison boundary. This preserves the existing configured-key semantics and constant-time primitive while making arbitrary Unicode header input an ordinary mismatch rather than an exception.

Rejected claims: the current evidence does not establish server-wide denial of service, information disclosure or compromise. The demonstrated defect is the authentication error-path failure.

Follow-up: do not mistake this narrow input fix for completion of the runtime-secret architecture. `AGENTS.md` already makes the credential-registry migration authoritative; that remains the next security/product gap after #543.

## TRACEABILITY

- Product boundary and runtime modes: `README.md`
- Security/config architecture authority: `AGENTS.md`
- Authentication middleware: `saas_web.py::require_api_key`, `get_configured_api_keys`
- Authentication regression: `tests/test_saas_web.py::TestApiKeyAuth`
- Existing durable SQLite pattern: `job_store.py`
- Repair lineage: PR #543
