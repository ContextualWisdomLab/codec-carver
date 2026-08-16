# API credential registry

## Decision

Codec Carver stores API-key verification material in a stdlib SQLite
registry (`credential_registry.py`, table `api_credentials`). Request
handlers in `saas_web.py` read only that registry. They do not call
`os.getenv` and they do not compare plaintext secrets from the process
environment.

`CODEC_CARVER_API_KEYS` remains **bootstrap transport**. Process start
(and tests) pass an explicit mapping into `bootstrap_from_mapping`. After
import, the plaintext keys exist only in the startup caller’s memory;
the database keeps SHA-256 digests, a lifecycle status (`active`,
`rotated`, `revoked`), and optional expiry.

## What to do next

1. Put current and next keys in `CODEC_CARVER_API_KEYS` only for the
   first start (or a dedicated bootstrap command). Restart loads them
   into `api_credentials`.
2. Send `X-API-Key` on every request except `GET /` and `GET /health`.
3. To rotate: call `CredentialRegistry.rotate` (or re-bootstrap the next
   key, then revoke the old id). Stop sending the retired secret.
4. Do not log registry listings, exception text, or headers; they are
   built to omit plaintext, and operators should keep it that way.

## Technical basis

Digital identity guidance treats a memorized or presented secret as a
verifier secret: store a one-way digest, compare in a way that does not
leak the secret through errors, and support authenticator lifecycle
(issue, rotate, revoke) with an explicit clock (Grassi et al., 2017).
OWASP’s API authentication guidance likewise requires rejecting
unauthenticated access to non-public operations without reflecting
credentials in responses (OWASP, 2023).

HMAC comparison (`hmac.compare_digest`) is the stdlib bound for
equal-length byte strings (Krawczyk et al., 1997). This registry hashes
both the stored secret and the presented header as UTF-8 SHA-256 hex
before comparison so mixed `str`/`bytes` cannot raise `TypeError` on
hostile Unicode, and every active digest is compared so a first-match
hit is not a timing signal.

The table name is two words (`api_credentials`). Columns depend only on
`credential_id` (3NF). Callers pass `now`; the store does not call
`datetime.now()`.

Local development stays fail-open when the registry has no verifiable
row so a laptop `uvicorn` still serves the upload form. Production
fail-closed bind policy (non-loopback + empty registry) is the next
slice and must not be implemented by reading extra environment
variables inside request handlers.

## Verification and rollback

- `python3 -m unittest tests.test_credential_registry tests.test_saas_web.TestApiKeyAuth tests.test_saas_web.TestCredentialWiring -v`
- Non-ASCII, overlong, duplicate, control-character, rotated, revoked,
  expired, concurrent-read, and secret-redaction cases must stay green.
- Roll back by restoring `saas_web.require_api_key` only if you also
  restore the tests; do not reintroduce request-time
  `os.environ.get("CODEC_CARVER_API_KEYS")`.

## References

Grassi, P. A., Garcia, M. E., & Fenton, J. L. (2017). *Digital identity
guidelines: Authentication and lifecycle management* (NIST Special
Publication 800-63B). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-63B

Krawczyk, H., Bellare, M., & Canetti, R. (1997). *HMAC: Keyed-hashing
for message authentication* (RFC 2104). Internet Engineering Task Force.
https://doi.org/10.17487/RFC2104

OWASP. (2023). *OWASP API security top 10 2023*. Open Worldwide
Application Security Project.
https://owasp.org/API-Security/editions/2023/en/0x11-t10/
