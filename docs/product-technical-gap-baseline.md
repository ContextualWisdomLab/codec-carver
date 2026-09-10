# Product / Technical Gap Baseline

This document records code-current buyer and engineering gaps for `codec-carver`. The repository remains a standalone audio/video conversion component whose generated outputs must preserve source safety, metadata semantics, and deterministic CLI behavior.

## Current collision-output contract

As of PR #557, `overwrite=False` means an output pathname is occupied when a directory entry already exists, including a dangling symbolic link whose target does not exist. `pathlib.Path.exists()` is insufficient for that namespace test because it follows the link target; `_resolve_collision()` therefore uses `os.lstat()` and selects the next numbered pathname.

Evidence on the PR branch:

- base: `main@47c6fd27de13b0da37a7db64697b869941909351`
- repaired descendant: `0721624d20c838e7ee9f0b8f705da8996f5c9f0c`
- regression: `tests/test_collision_namespace.py::ResolveCollisionNamespaceTests.test_dangling_symlink_consumes_name_when_overwrite_is_disabled`
- existing exhaustion and ordinary-collision behavior remains covered in `tests/test_media_shrinker.py`.

The initial PR described this change as an approximately 50% performance optimization. That performance claim is not part of acceptance: the referenced `test_perf_3.py` is not present at the current head and there is no checked-in, reproducible benchmark artifact demonstrating buyer-visible latency or throughput improvement. No general performance rule is therefore recorded for this change.

## Remaining publication gap

`_resolve_collision()` is a preflight choice, not an atomic publication primitive. `_execute_plan()` later performs another existence check and publishes the temporary artifact. Another process can create the chosen final directory entry between preflight and publication. A strong `overwrite=False` contract therefore still needs a realistic race regression and an atomic no-clobber publication design on supported platforms.

Acceptance for that follow-up is:

1. RED: pause publication after collision resolution, create the final pathname from a second actor, then prove the current path can replace or otherwise violate the no-clobber contract.
2. GREEN: publication fails closed without replacing the competing directory entry, preserves the completed temporary result according to the documented recovery policy, and does not weaken source-path protections.
3. Exact-head verification: targeted regression, full unit suite, security gates, and current-head review all pass on the same commit.
4. Portability: define Linux/macOS/Windows semantics explicitly; do not claim an atomic primitive is portable without evidence.

## Commercial acceptance

Collision handling is complete for a release only when ordinary files, dangling symlinks, numbered-name exhaustion, concurrent final-name creation, source/output aliasing, permission failures, and recovery from publication failure have explicit tests and operator-visible error semantics. Performance work must use a checked-in benchmark protocol and representative, right-cleared workload; synthetic microbenchmarks alone do not establish buyer-visible improvement.
