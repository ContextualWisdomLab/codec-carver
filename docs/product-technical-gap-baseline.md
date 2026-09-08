# Codec Carver product–technical gap baseline

Status: Proposed / code-current baseline  
Evidence generation before this document: `4f010e19f88b9d35a582d4acad96a3defeaf9026` on PR #543  
Protected target: `main@47c6fd27de13b0da37a7db64697b869941909351`  
Last reviewed: 2026-09-09

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
| Non-ASCII API-key handling | Direct `str` use with `hmac.compare_digest` can raise `TypeError` for non-ASCII input, converting an authentication rejection into a 500-class middleware failure. | PR #543 compares UTF-8 bytes and exercises a non-ASCII header through `require_api_key()`. Pre-document head `4f010e19...` had CI `34166584709`, fuzz `34166584713`, Security `34166584732`, and SAST `34166584700` terminal GREEN; CodeQL PR `34166584717` was terminal FAILURE at the separately owned central receipt boundary. Those predecessor results do not transfer to the document-restoration descendant. | One unchanged exact head must retain the middleware regression and this gap record, receive terminal-success applicable repository/central gates, and satisfy current-head review/thread requirements; non-ASCII wrong keys stay on the same 401 contract as other wrong keys. |
| Runtime credential source | `saas_web.py` still reads `CODEC_CARVER_API_KEYS` via the raw environment. `AGENTS.md` explicitly records this as a known architecture deviation and requires migration to a credential registry/KV. | Current production `get_configured_api_keys()` uses `os.environ`. The existing `JobStore` demonstrates a short-lived SQLite/WAL persistence pattern but is not itself a credential store. | Introduce a purpose-built credential registry with encrypted-at-rest secret values, bootstrap/import semantics, rotation/revocation tests and no request-time `os.getenv`/`os.environ` secret reads. Do not silently repurpose the jobs table. |
| Authentication lifecycle | A static comma-separated key list has no first-class key identity, activation/expiry, rotation receipt or audit metadata. | Current middleware treats configured keys as anonymous values. | Credential aggregate defines key identity/status/version, rotation without downtime, revocation, purpose scope and audit evidence; API behavior remains backward-compatible only through an explicit migration contract. |
| Commercial security baseline | The authentication baseline is not yet protected-branch truth. An intervening ordinary descendant after the first #543 baseline removed this file while retaining the source/test repair. | Fleet repair restores this file on #543 without rewriting that intervening history. | Keep this file code-current with authentication, media pipeline, operability and release evidence; future source/test descendants may not silently delete the canonical gap record. |

## PR #543 decision record

Problem: a non-ASCII `X-API-Key` can reach Python's `hmac.compare_digest` as `str`; that API rejects non-ASCII strings with `TypeError`, creating a request-time 500 path.

Decision: normalize both compared values to UTF-8 bytes at the comparison boundary. This preserves the existing configured-key semantics and constant-time primitive while making arbitrary Unicode header input an ordinary mismatch rather than an exception.

Rejected claims: the current evidence does not establish server-wide denial of service, information disclosure or compromise. The demonstrated defect is the authentication error-path failure. This is why duplicate PR #549's generated CRITICAL/DoS doctrine was not carried into the canonical lane.

Follow-up: do not mistake this narrow input fix for completion of the runtime-secret architecture. `AGENTS.md` already makes the credential-registry migration authoritative; that remains the next security/product gap after #543.

## TRACEABILITY

- Product boundary and runtime modes: `README.md`
- Security/config architecture authority: `AGENTS.md`
- Authentication middleware: `saas_web.py::require_api_key`, `get_configured_api_keys`
- Authentication regression: `tests/test_saas_web.py::TestApiKeyAuth`
- Existing durable SQLite pattern: `job_store.py`
- Repair lineage: PR #543; duplicate convergence: PR #549
