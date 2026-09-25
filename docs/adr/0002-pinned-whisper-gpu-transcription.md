# ADR 0002: Pinned Whisper-family GPU transcription

- Status: Accepted
- Date: 2026-08-25

## Context

GPU transcription must stay on an allowlisted accelerator and model revision so
cache hits, long-form chunking, and filename evidence remain reproducible. A
hosted or silently substituted runtime would change those identities.

## Decision

GPU transcription uses pinned Whisper-family models at the revisions named in
[`docs/architecture/gpu-transcription-rust-backend.md`](../architecture/gpu-transcription-rust-backend.md):

- Apple Silicon / Metal: `mlx-community/whisper-large-v3-turbo-q4` revision
  `660c343bbf4e52ac257f0b7d952e5388e6f93bef`
- NVIDIA / CUDA: `dropbox-dash/faster-whisper-large-v3-turbo` revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`

The path never calls Ollama and never silently falls back to CPU. Long-form
work uses bounded decode ranges with one-second overlap and timestamp midpoint
ownership rather than one peak-memory decode of the whole recording.

Speaker-aware MLX may use the pinned MOSS revision already named on `main` as
an implementation pin. That pin is not a scholarly source.

## Consequences

- Mutable model names or arbitrary Hub repositories are rejected before
  inference.
- Cache reuse requires the selected accelerator, allowlisted model, immutable
  revision, and requested language, not SHA identity alone.
- Interruptions resume from durable chunk checkpoints instead of re-decoding
  the entire waveform.

Supporting implementation notes remain in
[`docs/architecture/gpu-transcription-rust-backend.md`](../architecture/gpu-transcription-rust-backend.md)
and are non-normative once this ADR is the decision record.

## References

Radford, A., Kim, J. W., Xu, T., Brockman, G., McLeavey, C., & Sutskever, I.
(2022). *Robust speech recognition via large-scale weak supervision*. arXiv.
https://arxiv.org/abs/2212.04356

Repository PDF `docs/papers/2212.04356-whisper.pdf` is a supporting copy, not a
substitute locator.
