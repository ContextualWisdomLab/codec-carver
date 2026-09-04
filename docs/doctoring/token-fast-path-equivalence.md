# Token fast-path equivalence

## Status

**Historical / superseded for transcript summarization and transcript search.** This note records the behavioral-equivalence evidence for an earlier implementation optimization. PR #515 removes those tokenization/ranking paths from production decision authority because equivalence to an earlier heuristic does not establish that the heuristic itself is a valid selection or relevance model.

## Historical decision

The earlier implementation bypassed its regular-expression tokenizer only when the complete input token was non-empty and `str.isalnum()` was true; other inputs used the pre-existing regular expression. Curated multilingual cases and deterministic hostile-character samples established equivalence to the preceding implementation.

That evidence remains useful as a record of implementation equivalence, but it must not be cited as production authorization for token admission, transcript relevance, or summarization importance. `summarize.py` and `transcript_search.py` now fail closed for non-empty selection/retrieval until separately validated decision models exist.

## Technical basis of the retired optimization

Python defines `str.isalnum()` in terms of Unicode alphabetic and numeric character properties. Unicode Standard Annex #44 is the normative property-data reference used by implementations of Unicode-aware character APIs. Thompson's foundational regular-expression work explains why avoiding a matcher invocation can remove work. Neither source establishes the retired tokenizer, stopword handling, relevance scoring, or output ranking as a valid semantic decision rule.

## Historical verification evidence

- Curated cases covered Latin, accented Latin, Greek, Cyrillic, Korean, Japanese, full-width digits, punctuation, apostrophes, underscores, emoji, stop words, and empty text.
- A fixed seed generated 512 additional mixed-script and punctuation cases.
- The optimized functions were required to match executable reference copies of the previous algorithms.

These checks demonstrated implementation equivalence only. Current decision authority is documented in `docs/architecture/summarization-evidence-boundary.md`, `docs/architecture/transcript-retrieval-evidence-boundary.md`, and the corresponding doctoring notes.

## References

Python Software Foundation. (n.d.). *Built-in types: String methods* (Python 3.14 documentation). Retrieved August 7, 2026, from https://docs.python.org/3.14/library/stdtypes.html#str.isalnum

Thompson, K. (1968). Programming techniques: Regular expression search algorithm. *Communications of the ACM, 11*(6), 419–422. https://doi.org/10.1145/363347.363387

The Unicode Consortium. (2025). *The Unicode Standard, Version 17.0.0*. https://www.unicode.org/versions/Unicode17.0.0/

Whistler, K. (Ed.). (2025). *Unicode Standard Annex #44: Unicode Character Database* (Revision 36). The Unicode Consortium. https://www.unicode.org/reports/tr44/tr44-36.html
