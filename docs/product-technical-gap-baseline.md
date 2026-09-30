# Product technical gap baseline

Status: Proposed  
Last evaluated source commit: `7cffbbc2bfe3ec2a395864c80fd52782eb7d40f6`  
Pull request: [#655](https://github.com/ContextualWisdomLab/codec-carver/pull/655)

## Product and boundary

codec-carver owns media shrinking and its upload forms. Client-side byte limits provide early feedback but do not replace server validation. The repair keeps media and request truth in the backend and only changes when existing browser listeners are registered.

| Artifact | Current evidence | Status |
| --- | --- | --- |
| PRD / TRD | Repository product and technical docs were not re-authored by #655 | Existing baseline not revalidated |
| UML / ERD | No API or persistence model change | Not affected |
| Context Map | codec-carver remains the media-shrinking writer; no Core dependency added | Preserved |
| Gap | The script executed before batch controls existed, throwing on a null element and preventing later validation listeners | Repaired, verification pending |
| Action | Keep #655 Draft until exact-head checks and real-browser form evidence are complete | Open |

## Exact-head acceptance matrix

| Dimension | Evidence | Status |
| --- | --- | --- |
| Determinism | Listener-order regression asserts controls precede registrations | Local contract GREEN |
| Semantics | Native number-input `max` and server limit remain aligned at 5 GiB | Source evidence |
| Accessibility | `aria-invalid` and live preview remain wired after initialization | Source evidence only |
| Interaction | Single and batch preset/input listeners now register after both forms exist | Local contract GREEN |
| Responsive evidence | No desktop, intermediate, or mobile screenshots on the repaired head | FAIL |
| Locales | ko/en/ja/zh/vi/es/de/fr evidence is absent | FAIL |
| Large-data performance | No conversion or streaming algorithm changed | Not affected |
| Import/export and recovery | Upload submission, error, retry, busy, and form-state recovery need browser evidence | FAIL |

An applicable FAIL is not merge-ready. The PR remains Draft until the missing evidence is attached to an unchanged successor head.
