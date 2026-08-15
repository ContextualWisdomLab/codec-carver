# API-key comparison and bootstrap boundary

## Status

Accepted for the API-key middleware change carried by PR #376.

## Problem

`hmac.compare_digest()` accepts either two bytes-like values or two ASCII-only
strings. An HTTP client can supply a non-ASCII header value, so comparing the
raw header string to a configured API-key string can raise `TypeError` before
the middleware emits its ordinary authentication response. An attacker can
repeat that exceptional input to turn an invalid credential into an avoidable
availability failure rather than a bounded `401` response.

The previous request-time environment lookup also made the process environment
a mutable credential source. That mixed one-time bootstrap transport with the
runtime authentication authority and allowed an ambient environment change to
rotate credentials without an explicit application operation.

## Decision

1. API keys are held in a process-local, thread-safe credential registry.
2. `CODEC_CARVER_API_KEYS` is accepted only as one-time bootstrap transport.
3. The bootstrap value is removed from the environment after parsing.
4. Request handling reads only the registry and never rereads the environment.
5. Both the presented key and registered candidates are encoded as UTF-8 bytes
   before `hmac.compare_digest()`.
6. Invalid, missing, or non-ASCII presented keys return the same generic `401`
   payload and never echo credential material.
7. Empty registries preserve the existing opt-in, unauthenticated development
   mode. Production deployments must explicitly provision one or more keys.

This is a fail-closed exceptional-input repair consistent with CWE-754 and with
OWASP ASVS 5.0.0 authentication, secure-coding, and error-handling objectives.
It does not claim that API keys are a complete enterprise identity system.

## Runtime contract

```text
one-time trusted bootstrap
    -> parse and normalize keys
    -> remove transport environment variable
    -> atomically replace registry snapshot
    -> middleware reads immutable snapshot
    -> UTF-8 byte comparison
    -> success or generic 401
```

The registry never writes plaintext keys to disk, logs, response payloads, or
request traces. Key replacement requires an explicit trusted call to
`API_KEY_REGISTRY.set_keys()`.

## Verification contract

The regression suite must prove all of the following:

- an empty registry preserves the existing open-development behavior;
- missing and incorrect keys return `401` without secret disclosure;
- every registered key can authenticate;
- whitespace and empty bootstrap entries are normalized deterministically;
- the environment variable is consumed and removed during bootstrap;
- later environment changes cannot rotate runtime credentials;
- explicit registry replacement changes the accepted key set;
- a non-ASCII header returns `401` instead of raising `TypeError`;
- production statement and branch coverage remain at 100%;
- public production symbols retain complete docstrings.

## Distributed-deployment limit

The in-process registry is intentionally the smallest safe boundary for the
current single-process product. Multi-instance deployment requires a separately
reviewed credential-distribution adapter with versioned updates, instance
convergence evidence, rollback, and secret-manager authorization. Instances
must not poll ambient environment variables on every request. That distributed
rotation design is outside this bounded repair.

## References

Krawczyk, H., Bellare, M., & Canetti, R. (1997). *HMAC: Keyed-hashing for message authentication* (RFC 2104). Internet Engineering Task Force. https://doi.org/10.17487/RFC2104

OWASP Foundation. (2025). *OWASP Application Security Verification Standard 5.0.0*. https://owasp.org/www-project-application-security-verification-standard/

Python Software Foundation. (2026). *hmac—Keyed-hashing for message authentication*. Python 3.14.6 documentation. https://docs.python.org/3/library/hmac.html

The MITRE Corporation. (2026). *CWE-754: Improper check for unusual or exceptional conditions* (Version 4.20). https://cwe.mitre.org/data/definitions/754.html
