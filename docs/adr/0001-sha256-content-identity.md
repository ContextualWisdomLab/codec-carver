# ADR 0001: SHA-256 as content identity

- Status: Accepted
- Date: 2026-08-25

## Context

The GPU audio-library path must identify recordings and Sony TMK sidecars from
their bytes, reuse transcripts across renames or copies, and refuse mutations
when File Provider placeholders or restored inventory hints expose a digest
that current bytes have not verified.

## Decision

Every supported audio and TMK file that has locally available bytes receives a
full SHA-256 of those bytes. Exact-duplicate groups form only from that full
content hash. Transcripts are keyed by the full SHA-256. An unverified
placeholder hash never authorizes an exact-duplicate group or a
rename/quarantine mutation.

The digest is SHA-256 as specified in FIPS 180-4: a 256-bit message digest
computed over 512-bit blocks (Figure 1). This decision does not use SHA-1.

## Consequences

- Materialized sources are rehashed before a transcript cache hit, GPU call, or
  new mutation.
- A SHA restored from an inventory, journal, or same-path/same-size hint stays
  unverified until current bytes are hashed again.
- Audio and TMK duplicate groups stay separate.

Supporting implementation notes remain in
[`docs/architecture/gpu-transcription-rust-backend.md`](../architecture/gpu-transcription-rust-backend.md)
and are non-normative once this ADR is the decision record.

## References

National Institute of Standards and Technology. (2015). *Secure Hash Standard
(SHS)* (FIPS PUB 180-4). U.S. Department of Commerce.
https://doi.org/10.6028/NIST.FIPS.180-4

Live PDF (same document):
https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.180-4.pdf.
Repository copy `docs/standards/NIST.FIPS.180-4.pdf` is a supporting copy, not
a substitute locator.
