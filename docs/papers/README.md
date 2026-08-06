# Reference papers

## Fuzzing

- **`fuzzing-art-science-engineering-survey.pdf`** —
  Manès, V.-T., Han, H., Han, C., Cha, S. K., Egele, M., Schwartz, E. J., &
  Woo, M. (2019). The art, science, and engineering of fuzzing: A survey.
  *IEEE Transactions on Software Engineering, 47*(11), 2312–2331.
  https://doi.org/10.1109/TSE.2019.2946563

  Background for the coverage-guided fuzzing approach used in `fuzz/`: the
  Atheris harnesses are libFuzzer-style greybox fuzzers as characterised in
  Section 3 of the survey.

## Owned result storage and retention

- Cowan, C., Beattie, S., Wright, C., & Kroah-Hartman, G. (2001). RaceGuard:
  Kernel protection from temporary file race vulnerabilities. In *10th USENIX
  Security Symposium (USENIX Security 01)*. USENIX Association.
  https://www.usenix.org/conference/10th-usenix-security-symposium/raceguard-kernel-protection-temporary-file-race

  This peer-reviewed systems-security paper establishes why temporary resources
  created through non-atomic, predictable names are vulnerable to attacker races.
  It supports Codec Carver's use of an atomically created, unpredictable
  process-owned result root rather than a fixed shared `/tmp` directory name.

- Python Software Foundation. (2026). *tempfile — Generate temporary files and
  directories*. Python documentation.
  https://docs.python.org/3/library/tempfile.html

  The standard-library contract documents `mkdtemp()` as the secure primitive
  for creating temporary directories and makes cleanup the caller's explicit
  responsibility. Codec Carver therefore creates its result root with
  `tempfile.mkdtemp()` and owns deletion through its result lifecycle instead of
  assuming the operating system will remove application artifacts immediately.

- systemd project. (2026). *Using /tmp/ and /var/tmp/ safely*.
  https://systemd.io/TEMPORARY_DIRECTORIES/

  The primary systemd guidance describes private temporary namespaces/directories
  and age-based cleanup for temporary data. It supports treating temporary
  storage as an explicit ownership and lifecycle boundary rather than a globally
  trusted shared directory.

- Google Cloud. (2026). *Cleanup policy overview: Artifact Registry*.
  https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy-overview

  The primary service documentation defines age-based delete policies for
  artifacts. Codec Carver applies the same lifecycle principle locally: completed
  async outputs receive a bounded retention window and are eligible for deletion
  independently of whether a client ever downloads them. The local implementation
  additionally removes the corresponding durable job record so filesystem bytes
  and metadata do not diverge.

These references justify the security and lifecycle *principles*, not the exact
24-hour product value. `RESULT_RETENTION_SECONDS` is a Codec Carver operational
policy chosen to bound storage consumption while leaving a practical download
window; changing that value requires product/operations review plus retention
regression tests.
