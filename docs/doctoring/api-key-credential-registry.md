# API-key credential registry boundary

## Decision

Codec Carver treats `CODEC_CARVER_API_KEYS` as a deployment-time bootstrap
transport, not as the runtime credential source. During service initialization,
`bootstrap_codec_carver_api_keys()` copies the value into the process-local
`CredentialRegistry`. Request middleware subsequently reads only the registry.
Changing the process environment after bootstrap therefore cannot silently
change the authentication boundary.

This design intentionally does **not** persist API keys in the SQLite job store.
The job database has no credential-storage contract or at-rest encryption key,
so writing reusable API-key material there would create a new plaintext-at-rest
secret surface. The registry interface is deliberately small so a future
external secret manager, sidecar, or platform KV adapter can populate the same
runtime boundary without changing request authentication logic.

## Security properties

- Credential material is not read from mutable process environment variables on
  each request.
- Registry access is protected by a re-entrant lock so concurrent requests and
  controlled credential replacement cannot observe partially updated state.
- Credential names are validated and blank names fail closed.
- API-key comparison remains constant-time through `hmac.compare_digest` over
  UTF-8 bytes, so non-ASCII attacker input is rejected without the `TypeError`
  denial-of-service path that motivated PR #361.
- An absent or explicitly empty API-key bundle preserves the existing opt-in
  authentication mode. Deployments that require mandatory authentication must
  provision a non-empty bundle before service start and verify the protected
  endpoint contract during readiness checks.
- Runtime rotation is an explicit control-plane action. Operators must update
  the registry through the approved bootstrap/secret-manager integration or
  restart the service with newly provisioned bootstrap material; editing the
  process environment behind a running worker is not a supported rotation path.

## Verification contract

`tests/test_credential_registry.py` pins registry set/get/delete behavior,
rejects ambiguous names, and proves that mutating the bootstrap mapping after a
copy does not alter runtime state. `TestApiKeyAuth` in
`tests/test_saas_web.py` uses registry fixtures rather than environment-variable
patches and proves that an environment-only replacement key is rejected while
the registered key continues to authenticate. The pre-existing non-ASCII test
continues to prove that malformed Unicode input returns HTTP 401 instead of
raising through `compare_digest`.

The first registry regression test was committed before the implementation so
review history preserves the RED→GREEN sequence. The final merge gate remains
exact-head CI/security checks plus repository-required independent approval.

## Standards and research basis

NIST SP 800-57 Part 1 Revision 5 remains the current final NIST general
key-management recommendation. NIST has published Revision 6 only as an Initial
Public Draft; it adds an expanded discussion of keying material storage, but it
is not substituted for the current final publication. The separation between
bootstrap transport and runtime credential use follows the broader lifecycle
principle that sensitive keying material requires explicit protection, use,
replacement, and destruction boundaries.

OWASP ASVS 5.0 secret-management requirements call for a secrets-management
solution to create, store, control access to, and destroy backend secrets. The
process-local registry in this PR is not represented as a full enterprise vault;
it is the application boundary that removes per-request environment reads and
provides a stable integration point for such a vault or platform KV.

Krause et al. (2023) found that secret leakage is a recurring developer problem
and emphasized low-adoption-cost prevention and remediation mechanisms. Keeping
bootstrap compatibility while moving request-time consumption behind one small
registry minimizes deployment disruption while closing the evidenced runtime
configuration coupling.

## References

Barker, E. (2020). *Recommendation for key management: Part 1—General*
(NIST Special Publication 800-57 Part 1 Revision 5). National Institute of
Standards and Technology. https://doi.org/10.6028/NIST.SP.800-57pt1r5

Barker, E., & Barker, W. (2025). *Recommendation for key management: Part 1—General*
(Initial Public Draft, NIST Special Publication 800-57 Part 1 Revision 6).
National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-57pt1r6.ipd

Krause, A., Klemmer, J. H., Huaman, N., Wermke, D., Acar, Y., & Fahl, S.
(2023). Pushed by accident: A mixed-methods study on strategies of handling
secret information in source code repositories. In *32nd USENIX Security
Symposium (USENIX Security 23)* (pp. 2527–2544). USENIX Association.
https://www.usenix.org/conference/usenixsecurity23/presentation/krause

OWASP Foundation. (2025). *OWASP Application Security Verification Standard
5.0: V13.3 Secret management*. https://cornucopia.owasp.org/taxonomy/asvs-5.0/13-configuration/03-secret-management
