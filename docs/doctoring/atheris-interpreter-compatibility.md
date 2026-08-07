# Atheris interpreter-compatible fuzz lock

## Incident

The product fuzz lane uses CPython 3.12, while the central OpenCode evidence
image currently evaluates Python repositories on CPython 3.14. The previous
Atheris 3.0.0 lock did not publish a CPython 3.14 wheel. A binary-only,
hash-enforced installation therefore failed before repository tests or
production docstring checks could run.

This is a repository dependency compatibility defect, not a reason to weaken
the central fail-closed installer or reinterpret missing coverage evidence as
success.

## Decision

Codec Carver pins Atheris 3.1.0 in both the human-maintained fuzz input and the
hash lock. The lock records only the official PyPI manylinux x86-64 wheels for
CPython 3.12, 3.13, and 3.14:

| Interpreter | SHA-256 |
|---|---|
| CPython 3.12 | `ec5e11f21a4c197fe91f7aea2b2de88e623c73a21fc07b105ac6329a1588457b` |
| CPython 3.13 | `f8a9f51ce8369026e8eb7b7174835e8c4c85a1a6db5d9add36c15100779d2a39` |
| CPython 3.14 | `315a0b5c819852b1ffe1ca72efc389c7724881f2c33e4aacb8c6bcec49bd5011` |

The ordinary bounded fuzz targets remain on CPython 3.12. A separate
compatibility matrix installs the exact same lock with
`--require-hashes --only-binary=:all:` on CPython 3.12 and 3.14, imports
Atheris, and runs `pip check`. This proves both the product execution lane and
the central review lane without compiling pull-request-selected native source.

## Security and supply-chain boundary

- Package name and version are exact.
- Every accepted artifact is bound to an official published SHA-256 digest.
- Source distributions and local builds are rejected in CI.
- No mutable URL, alternate index, unpinned transitive requirement, or
  pull-request-generated artifact is accepted.
- The lock update does not change fuzz target semantics, time budgets, corpus
  retention, crash artifact handling, reviewer credentials, or branch
  protection.

## Verification and rollback

- `tests/test_dependency_lock.py` proves direct runtime pin/lock consistency,
  exact Atheris input/lock identity, exact artifact digests, and the two-lane CI
  contract.
- Both interpreter matrix entries must install and import the wheel.
- The existing property suite and bounded Atheris targets must pass.
- Central exact-head coverage and production docstring evidence must be rerun;
  predecessor-head failure or success does not transfer.
- Rollback requires another exact Atheris release with verified binary wheels
  for every active interpreter lane. Restoring an interpreter-incompatible
  lock or permitting source builds is not an acceptable rollback.

## References

Atheris maintainers. (2026). *Atheris 3.1.0* [Python package]. Python Package
Index. https://pypi.org/project/atheris/3.1.0/

Python Packaging Authority. (n.d.). *Platform compatibility tags*. Python
Packaging User Guide. Retrieved August 7, 2026, from
https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/

Python Packaging Authority. (n.d.). *Recording the direct URL origin of
installed distributions*. Python Packaging User Guide. Retrieved August 7,
2026, from
https://packaging.python.org/en/latest/specifications/direct-url-data-structure/
