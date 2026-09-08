# Codec Carver

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/codec-carver)

**Turn long recordings into durable, metadata-preserving audio artifacts without losing the source.**

Codec Carver is a Python CLI and evidence-aware recording-library toolkit. It converts supported recordings into size-bounded FLAC/Opus output, splits long audio at bounded duration points, preserves source metadata, and can optionally add transcription, library inventory, duplicate quarantine, and TMK/VAD reconciliation workflows.

The product boundary is deliberately conservative: source recordings remain authoritative, generated output is written separately, and evidence used for later library mutations stays explicit rather than being inferred from filenames or model output.

## Choose the workflow you need

- **Convert recordings** — produce metadata-preserving FLAC/Opus artifacts under explicit size and duration limits.
- **Split long audio** — prefer detected silence before a duration boundary and fall back to a bounded hard split when necessary.
- **Add searchable transcripts** — opt into transcription sidecars without making transcription failure invalidate a completed conversion.
- **Curate a recording library** — use the Rust-backed library workflow for hashing, inventory, exact-duplicate quarantine, bounded materialization, and evidence-aware renaming/reconciliation.
- **Expose an integration surface** — optionally run the FastAPI upload service or MCP integration when those dependencies are installed.

Codec Carver is not a media server, cloud-sync authority, or irreversible-delete tool. Provider state, authentication, access policy, model licensing, and downstream publication remain separate responsibilities.

## Quick start

Prerequisites are Python 3.10+ and `ffmpeg`/`ffprobe` on `PATH`.

For a source checkout:

```bash
pip install -e .
codec-carver /path/to/recordings --execute --output-dir under_2gb
```

Use a generated-only output directory so originals and generated artifacts remain easy to distinguish. Inspect help before a consequential batch:

```bash
codec-carver --help
```

For the optional web surface:

```bash
pip install -e ".[web]"
docker build -t codec-carver .
docker run -p 8000:8000 codec-carver
```

For MCP integration:

```bash
pip install -e ".[mcp]"
```

## Common usage

A repeatable conversion can be stored in `.codec-carver.json` in the scan root or current working directory. CLI options override config values, while the scan root and `--execute` remain intentionally non-configurable so a config file cannot silently turn a dry run into a mutation.

Example:

```json
{
  "flac_all": true,
  "exclude_dir_prefix": ["split_over"],
  "max_duration_seconds": 14400,
  "workers": 2,
  "output_dir": "under_2gb"
}
```

Metadata overrides such as `--set-title`, `--set-artist`, `--set-album`, and `--set-comment` are passed to `ffmpeg` as individual arguments rather than through a shell. Output formats include the default FLAC/Opus policy plus explicit FLAC, Opus, AAC, and MP3 modes where supported by the current CLI.

## Recording-library curation

The importable library API is `audio_library.AudioLibrary`; the CLI entry point is `codec-carver-library`.

The library path combines Python orchestration with a Rust backend for byte-heavy inventory and mutation work. It uses SHA-256-bound evidence, keeps exact-duplicate quarantine recoverable, and records the provenance needed to reconcile later TMK or transcript information without silently rewriting source history.

Apple Silicon/MLX, CUDA transcription, iCloud/File Provider staging, TMK hydration, description review, backend pinning, and low-disk operating procedures are intentionally kept out of the customer landing page. They remain available in the preserved [advanced operations reference](docs/advanced-operations.md) and the architecture documentation.

## Architecture and safety boundary

The major responsibilities are:

1. **Conversion CLI** — scans selected input, plans conversion/splitting, and writes generated media separately from source.
2. **Library orchestration** — manages inventory, transcript evidence, plans, and recoverable mutation state.
3. **Rust backend** — performs byte-heavy scanning, hashing, bounded filesystem work, and mutation primitives used by the library path.
4. **External tools/models** — `ffmpeg`/`ffprobe`, Python/Rust packages, model runtimes, model weights, and provider services remain independent dependencies with their own authority and licensing.

Start with [segmentation and reconciliation](docs/architecture/segmentation-reconciliation.md) for the TMK/VAD evidence contract. The deeper GPU/Rust design is documented in [the library architecture](docs/architecture/gpu-transcription-rust-backend.md).

## Verification and status

Run the repository test surface from the source tree:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile media_shrinker.py
```

The package metadata currently identifies source version `0.1.0`. Treat that as source metadata, not by itself as proof of a published release, supported deployment, benchmark, customer adoption, or certification. GitHub Releases and exact protected-branch evidence are the authority for shipped artifacts when such artifacts exist.

Current source also contains CI, fuzzing, SAST, and security workflows; use the results for the exact revision you intend to ship rather than predecessor-head evidence.

## Documentation

- [Documentation home](docs/index.md)
- [Advanced operations reference](docs/advanced-operations.md)
- [Segmentation and reconciliation](docs/architecture/segmentation-reconciliation.md)
- [GPU transcription / Rust backend architecture](docs/architecture/gpu-transcription-rust-backend.md)
- [Security policy](SECURITY.md)
- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/codec-carver)

## Contributing and support

Keep product-facing changes evidence-bound and preserve the separation between source recordings, generated output, library evidence, and external provider/model authority. Changes to filesystem mutation, model provenance, or source identity should include focused regression tests and update the owning architecture document rather than expanding the README into an operator runbook again.

For suspected vulnerabilities, follow `SECURITY.md` and avoid public disclosure before coordinated review.

## License

Codec Carver source declares the **MIT License** in `pyproject.toml`; this documentation branch carries the matching root [LICENSE](LICENSE). The MIT grant applies to Codec Carver-authored source and documentation.

External tools and dependencies—including `ffmpeg`/`ffprobe`, Python/Rust packages, model runtimes, model weights, and provider services—retain their own licenses and terms and are not relicensed by this repository. A permissive repository license is not evidence that every optional model, binary, or service is approved for a particular commercial distribution.
