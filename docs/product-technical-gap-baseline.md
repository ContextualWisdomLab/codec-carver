# Codec Carver product–technical gap baseline

Status: Proposed / code-current baseline  
Evidence generation before this document: `e2b7e75b22d7f3365a94c06fd4b3679ebe1ae2f6` on PR #543  
Protected target: `main@47c6fd27de13b0da37a7db64697b869941909351`  
Last reviewed: 2026-09-12

## Product boundary

Codec Carver owns media carving/transcoding, metadata-preserved outputs, long-recording segmentation and the optional web/MCP service boundary used to feed STT and omni-modal pipelines. Byte-heavy library curation is Rust-backed where practical; Python remains the web/orchestration and compatibility boundary described by the repository's current implementation.

The SaaS web service is a separate application boundary around those media operations. Authentication must fail closed before any upload/conversion work is admitted.

## Authentication invariants

- When API-key authentication is configured, every non-root request must present a matching key or receive the ordinary `401 {"error":"Invalid or missing API key"}` response.
- Malformed, Unicode or raw-ASGI obs-text header values must not escape the authentication middleware as request-time exceptions.
- A rejected credential must not execute the downstream `call_next` application path.
- Secret comparison retains a constant-time primitive and does not reflect configured key material in responses.
- Runtime secrets/config must ultimately be read from the repository-approved credential registry/KV. Raw environment access is bootstrap transport only, not the target runtime architecture.

## Current gap register

| Gap | Buyer/control impact | Current evidence | Acceptance |
| --- | --- | --- | --- |
| Non-ASCII API-key handling | Direct `str` use with `hmac.compare_digest` can raise `TypeError` for non-ASCII input, converting an authentication rejection into a 500-class middleware failure. | PR #543 normalizes compared values to UTF-8 bytes. The current branch also carries `tests/test_api_key_header_boundary.py`, which constructs a raw ASGI `X-API-Key: b"\xff"`, requires the ordinary 401 body, verifies configured secret non-reflection, and proves `call_next` is not invoked. | One unchanged exact head must retain both middleware and raw-ASGI regressions, receive terminal-success applicable repository/central gates, and satisfy current-head review/thread requirements. Predecessor GREEN does not transfer. |
| Runtime credential source | `saas_web.py` still reads `CODEC_CARVER_API_KEYS` via the raw environment. `AGENTS.md` records this as an architecture deviation and requires migration to a credential registry/KV. | Current production `get_configured_api_keys()` uses `os.environ`. The existing `JobStore` demonstrates a short-lived SQLite/WAL persistence pattern but is not itself a credential store. | Introduce a purpose-built credential registry with encrypted-at-rest secret values, bootstrap/import semantics, rotation/revocation tests and no request-time `os.getenv`/`os.environ` secret reads. Do not silently repurpose the jobs table. |
| Authentication lifecycle | A static comma-separated key list has no first-class key identity, activation/expiry, rotation receipt or audit metadata. | Current middleware treats configured keys as anonymous values. | Credential aggregate defines key identity/status/version, rotation without downtime, revocation, purpose scope and audit evidence; API behavior remains backward-compatible only through an explicit migration contract. |
| Commercial security baseline | An intervening ordinary descendant after the first #543 baseline removed this file while retaining the source repair and adding the raw-ASGI regression. | Fleet repair restores the baseline without rewriting intervening history and updates it to the current authentication boundary. | Future source/test descendants must keep this gap record code-current; branch-local test additions or dependency work may not silently delete the canonical buyer/control baseline. |

## PR #543 decision record

Problem: a non-ASCII `X-API-Key` can reach Python's `hmac.compare_digest` as `str`; that API rejects non-ASCII strings with `TypeError`, creating a request-time 500 path. A raw ASGI obs-text header is a stronger boundary probe because it exercises Starlette/FastAPI header decoding before the comparison and proves rejected credentials do not reach application work.

Decision: normalize both compared values to UTF-8 bytes at the comparison boundary and keep `hmac.compare_digest`. Preserve the existing 401 response contract. The raw-ASGI regression is adopted as executable acceptance evidence; dependency and generated-doctrine deltas from duplicate branches are not imported.

Rejected claims: current evidence does not establish server-wide denial of service, information disclosure or compromise. The demonstrated defect is the authentication error-path failure. Duplicate CRITICAL/DoS wording is not part of the product contract.

Follow-up: this narrow input repair does not complete runtime-secret architecture. The credential-registry migration remains the next security/product gap after #543.

## TRACEABILITY

- Product boundary and runtime modes: `README.md`
- Security/config architecture authority: `AGENTS.md`
- Authentication middleware: `saas_web.py::require_api_key`, `get_configured_api_keys`
- Middleware regression: `tests/test_saas_web.py::TestApiKeyAuth`
- Raw ASGI boundary regression: `tests/test_api_key_header_boundary.py`
- Existing durable SQLite pattern: `job_store.py`
- Repair/convergence lineage: PR #543; duplicates #549, #555, #559
