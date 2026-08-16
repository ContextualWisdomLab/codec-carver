# Architecture

Codec Carver is a standalone conversion service that also works as a git
submodule. The Python CLI, FastAPI upload UI, MCP tool, and Rust
`codec-carver-core` binary can run alone. When naruon or another
ContextualWisdomLab service imports the module, `convert_file` is the
stable in-process port.

```text
                    +------------------+
   browser / API -->| saas_web.py      |  GET /  GET /health
                    | require_api_key  |----> credential_registry
                    | /shrink  /jobs   |      (api_credentials)
                    +--------+---------+
                             |
                             v
                    media_shrinker.py  ----> ffmpeg / ffprobe
                             |
              +--------------+--------------+
              |                             |
        job_store.py                  rust-core/
        (jobs table;                  codec-carver-core
         rename to                    (library CLI)
         conversion_jobs is
         follow-up debt)
```

## Credential port

`credential_registry.CredentialRegistry` is the provider-neutral
credential port. Other CWL services can depend on this module without
importing FastAPI. Bootstrap transport may be an environment snapshot;
request-time verification may not. See
`docs/doctoring/api-credential-registry.md`.

## Core ERD (auth + jobs)

```text
api_credentials
  credential_id PK
  key_digest UK
  lifecycle_status
  created_at
  updated_at
  rotated_at
  revoked_at
  expires_at

jobs                -- existing; one-word name is known debt
  id PK
  status
  created_at
  updated_at
  output_path
  output_name
  error
  temp_dir
```

Both tables are in 3NF: non-key attributes depend only on the primary
key. Usage metering still keys rows by plaintext `api_key` (`usage`);
rebinding that table to `credential_id` is a later migration.

## Next actions

1. Land this registry. Close HMAC-only sentinels (#376, #421) as
   superseded once compare_digest no longer sees raw Unicode headers.
2. Keep Cloud Agent environment work on #427; do not mix it here.
3. Rename `jobs` → `conversion_jobs` in a dedicated migration.
4. Add production fail-closed bind policy without request-time env reads.
