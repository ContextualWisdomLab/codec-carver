# Fuzzing Codec Carver

Coverage-guided fuzz harnesses for the highest-value **untrusted-input**
surfaces in `media_shrinker.py` — the code that turns output from external
`ffmpeg`/`ffprobe` subprocesses (driven by attacker-supplied media) into
in-process data structures.

## Tooling & licenses

| Tool | Purpose | License |
| ---- | ------- | ------- |
| [Atheris](https://github.com/google/atheris) | coverage-guided (libFuzzer) fuzzing | Apache-2.0 |
| [Hypothesis](https://hypothesis.readthedocs.io/) | property-based tests in the normal suite | MPL-2.0 |

Both are permissive (no GPL/AGPL). Atheris supports CPython 3.6–3.12.

## Targets

Surfaces were located with CodeGraph
(`codegraph explore "parse ffmpeg output silencedetect duration probe metadata"`),
which flagged the three parsing/assembly functions below as the untrusted-input
entry points.

| Harness | Function under test | Property asserted |
| ------- | ------------------- | ----------------- |
| `fuzz_parse_silencedetect.py` | `parse_silencedetect_intervals(stderr)` | never raises on arbitrary text; every interval is finite with `0 <= start < end` |
| `fuzz_parse_probe_payload.py` | `_parse_probe_payload(payload, …)` | returns a valid `MediaProbe` or raises `MediaShrinkerError` — never `KeyError`/`TypeError`/`OverflowError` |
| `fuzz_build_segments.py` | `build_segments(duration, max, silence)` | split plan is contiguous, gap-free, covers `[0, duration]`, and each segment is non-empty and within the cap |

Seed corpora live in `fuzz/corpus/<target>/`.

## Running locally

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# One target, ~60s:
python fuzz/fuzz_parse_silencedetect.py -max_total_time=60 fuzz/corpus/parse_silencedetect

# Replay a specific crash reproducer:
python fuzz/fuzz_parse_probe_payload.py crash-<hash>
```

The property-based mirror of these invariants runs in the ordinary test suite
(`tests/test_fuzz_properties.py`) and needs only Hypothesis, so it executes on
every Python version in CI.

## CI

`.github/workflows/fuzz.yml` runs each target for a bounded budget
(90s/target on PRs, 10min/target nightly) plus the property/regression suite.
Crash reproducers are uploaded as build artifacts on failure.

## Findings

Fuzzing surfaced a real robustness bug: a large-exponent numeric field in an
`ffprobe` JSON payload (valid JSON, e.g. `1e999`) is parsed by `json.loads`
into `inf`, which made `_first_int` raise an unhandled `OverflowError`. The
coercers now skip non-finite values; see `NonFiniteRegressionTests` in
`tests/test_fuzz_properties.py`.
