# Cloud Agent environment bootstrap

## Decision

Codec Carver commits a repository-managed Cloud Agent environment at
`.cursor/environment.json`. `install` installs hash-locked Python dependencies,
adds `rustfmt` to the pinned minimal Rust toolchain, and builds
`codec-carver-core`. `start` rebuilds that binary only when a fresh checkout
wiped `rust-core/target`, then brings up `saas_web:app` on `0.0.0.0:8000` and
**waits** until `GET /health` succeeds.

Agents should treat a green `start` as “the upload UI is listening.” A
`nohup` without a readiness wait is not an environment start.

## Technical basis

Cursor resolves environment configuration from the checked-out
`.cursor/environment.json` before any dashboard-managed personal or team
environment (Cursor, n.d.). The public schema rejects undeclared fields,
including `$schema`, so this repository does not add one.

Python package integrity follows pip hash-checking mode: install the lock
file with `--require-hashes`, then link the editable tree with `--no-index
--no-deps` so the index cannot substitute a different wheel (Python Software
Foundation, n.d.). That pairing is the same contract CI uses and is the
minimum SLSA-aligned control this repository can apply without a hermetic
build service (SLSA, 2023).

Fail-closed toolchain setup follows NIST SSDF PW.4 / PW.8: produce a
repeatable build environment and do not continue when a required verification
tool (`rustfmt`) is missing (Souppaya et al., 2022).

`GET /health` is a liveness probe, not a substitute for job-store or ffmpeg
readiness. Load balancers and Cloud Agent `start` share that URL so a crashed
uvicorn cannot look like a successful boot.

## Verification and rollback

- `bash -n .cursor/install.sh .cursor/start.sh` must succeed.
- `tests/test_cloud_agent_environment.py` locks the JSON fields, the hash-locked
  pip lines, rustfmt fail-closed install, and the `/health` wait.
- `GET /health` stays auth-exempt and returns
  `{"status": "ok", "service": "codec-carver"}` whether or not API keys are
  configured.
- Roll back by restoring the previous scripts; do not reintroduce `|| true` on
  rustfmt or a `nohup` that returns before the probe succeeds.

## Next action

After this lands, mark the Cloud Agent environment draft ready for review and
close the earlier environment-only PR that lacked the readiness contract.

## References

Cursor. (n.d.). *Cloud Agents environment schema*. Retrieved August 16, 2026,
from https://cursor.com/schemas/environment.schema.json

Python Software Foundation. (n.d.). *Secure installs: Hash-checking mode*
(pip documentation). Retrieved August 16, 2026, from
https://pip.pypa.io/en/stable/topics/secure-installs/

SLSA. (2023). *Supply-chain Levels for Software Artifacts (SLSA) v1.0*.
https://slsa.dev/spec/v1.0/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) Version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
