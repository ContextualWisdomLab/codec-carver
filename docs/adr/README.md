# Accepted architecture decision records

These ADRs record decisions already true on default `main` for the GPU
audio-library path. They do not change product behavior.

Once an ADR is the decision record, the architecture notes are supporting
detail only (non-normative):

- [`docs/architecture/gpu-transcription-rust-backend.md`](../architecture/gpu-transcription-rust-backend.md)
- [`docs/architecture/segmentation-reconciliation.md`](../architecture/segmentation-reconciliation.md)

| ADR | Title | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-sha256-content-identity.md) | SHA-256 as content identity | Accepted | 2026-08-25 |
| [0002](0002-pinned-whisper-gpu-transcription.md) | Pinned Whisper-family GPU transcription | Accepted | 2026-08-25 |
| [0003](0003-tmk-vad-fixed-duration-precedence.md) | TMK, then VAD, then fixed-duration precedence | Accepted | 2026-08-25 |

Codec Carver remains independently runnable. These records describe this leaf
product only.
