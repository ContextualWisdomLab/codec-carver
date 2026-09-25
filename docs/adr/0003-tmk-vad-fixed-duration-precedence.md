# ADR 0003: TMK, then VAD, then fixed-duration precedence

- Status: Accepted
- Date: 2026-08-25

## Context

Long recordings need bounded GPU decode ranges. Sony TMK markers, chapter
metadata, silence, and fixed cuts are not equally reliable. A late TMK must
not discard a resumable fallback transcript, and isolated decoder text over
non-speech must not become an authoritative title.

## Decision

Evidence precedence for segmentation is:

1. Verified Sony TMK markers
2. Reliable chapter/marker metadata
3. VAD/silence
4. Bounded fixed-duration resource fallback

Five-minute cuts are checkpoint and memory limits, not semantic turns. When a
TMK arrives after a fallback, the plan promotes the existing transcript if the
boundary vectors are equivalent, or names only the affected intervals for GPU
reprocessing.

The quality gate that filters repetitive/background non-speech follows the
long-form/non-speech hallucination risk documented by Yan et al. (IWSLT 2024)
and the false-positive filtering architecture evaluated by Bondarenko et al.
(NAACL 2025).

## Consequences

- A pending iCloud sidecar is `tmk_pending_materialization`; a genuinely
  unavailable sidecar is `tmk_unavailable`. Unresolved TMKs do not block GPU
  audio work.
- Optional VAD may shift a checkpoint inside a configured window and records
  that shift; VAD failure does not block fixed-range recovery.
- Segment timestamps own the final transcript; equal-text, timestamp-
  overlapping boundary duplicates are removed, while repeated speech separated
  in time is retained.

Supporting implementation notes remain in
[`docs/architecture/segmentation-reconciliation.md`](../architecture/segmentation-reconciliation.md)
and
[`docs/architecture/gpu-transcription-rust-backend.md`](../architecture/gpu-transcription-rust-backend.md)
and are non-normative once this ADR is the decision record.

## References

Yan, B., Fernandes, P., Tian, J., Ouyang, S., Chen, W., Livescu, K., Li, L.,
Neubig, G., & Watanabe, S. (2024). CMU’s IWSLT 2024 offline speech translation
system: A cascaded approach for long-form robustness. In *Proceedings of the
21st International Conference on Spoken Language Translation (IWSLT 2024)*
(pp. 164–169). Association for Computational Linguistics.
https://doi.org/10.18653/v1/2024.iwslt-1.22

Bondarenko, I., Grebenkin, D., Sedukhin, O., Klementev, M., Derunets, R., &
Budneva, L. (2025). Pisets: A robust speech recognition system for lectures
and interviews. In *Proceedings of the 2025 Conference of the Nations of the
Americas Chapter of the Association for Computational Linguistics: Human
Language Technologies (Volume 3: Industry Track)* (pp. 988–997). Association
for Computational Linguistics. https://doi.org/10.18653/v1/2025.naacl-industry.74
