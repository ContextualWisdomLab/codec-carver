# Token fast-path equivalence

## Decision

Codec Carver may bypass its regular-expression tokenizer only when the complete
input token is non-empty and `str.isalnum()` is true. All other inputs continue
through the pre-existing regular expression. The optimization therefore narrows
the execution path without changing the accepted token language.

The implementation does not claim a universal regular-expression speedup.
Instead, curated multilingual examples and a deterministic hostile-character
sample compare the optimized functions against executable reference copies of
the previous algorithms. Any semantic difference fails the test suite.

## Technical basis

Python defines `str.isalnum()` in terms of Unicode alphabetic and numeric
character properties. Unicode Standard Annex #44 is the normative property-data
reference used by implementations of Unicode-aware character APIs. Regular
expression matching remains the fallback for punctuation, whitespace,
underscores, apostrophes, emoji boundaries, and mixed strings. Thompson's
foundational regular-expression work explains why avoiding a matcher invocation
can remove work, but the release decision here rests on repository-specific
behavioral equivalence tests rather than an extrapolated benchmark claim.

## Verification and rollback

- Curated cases cover Latin, accented Latin, Greek, Cyrillic, Korean, Japanese,
  full-width digits, punctuation, apostrophes, underscores, emoji, stop words,
  and empty text.
- A fixed seed generates 512 additional mixed-script and punctuation cases.
- Both the summarizer and transcript-search tokenizer must exactly match the
  pre-optimization reference outputs.
- The complete repository test suite, production docstring gate, security
  checks, and fuzz checks remain required.
- Roll back by restoring the unconditional regular-expression calls; do not
  weaken or delete the equivalence tests.

## References

Python Software Foundation. (n.d.). *Built-in types: String methods* (Python
3.14 documentation). Retrieved August 7, 2026, from
https://docs.python.org/3.14/library/stdtypes.html#str.isalnum

Thompson, K. (1968). Programming techniques: Regular expression search
algorithm. *Communications of the ACM, 11*(6), 419–422.
https://doi.org/10.1145/363347.363387

The Unicode Consortium. (2025). *The Unicode Standard, Version 17.0.0*.
https://www.unicode.org/versions/Unicode17.0.0/

Whistler, K. (Ed.). (2025). Unicode Standard Annex #44: Unicode Character
Database (Revision 36). The Unicode Consortium.
https://www.unicode.org/reports/tr44/tr44-36.html
