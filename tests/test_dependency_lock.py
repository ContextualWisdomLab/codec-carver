"""Regression tests for dependency-lock consistency and interpreter support."""

from __future__ import annotations

import re
import unittest
from ast import literal_eval
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXACT_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)"
)
SHA256_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)")
ATHERIS_HASHES = {
    "ec5e11f21a4c197fe91f7aea2b2de88e623c73a21fc07b105ac6329a1588457b",
    "f8a9f51ce8369026e8eb7b7174835e8c4c85a1a6db5d9add36c15100779d2a39",
    "315a0b5c819852b1ffe1ca72efc389c7724881f2c33e4aacb8c6bcec49bd5011",
}


def workflow_job(path: Path, job_name: str) -> str:
    """Return one top-level workflow job after rejecting unsafe run scalars.

    The project intentionally has no YAML runtime dependency.  This focused
    parser validates the YAML ambiguity that can turn an unquoted ``run``
    command into a mapping, then scopes assertions to one job by indentation.
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        match = re.match(r"^(?P<indent>\s*)run:\s+(?P<value>.+)$", line)
        if not match:
            continue
        value = match.group("value")
        if value[0] not in "'\"|>" and ": " in value:
            raise AssertionError(
                f"{path}:{line_number}: quote a run scalar containing ': '"
            )

    job_header = f"  {job_name}:"
    try:
        start = lines.index(job_header)
    except ValueError as exc:
        raise AssertionError(f"missing workflow job: {job_name}") from exc
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if re.match(r"^  [A-Za-z0-9_-]+:\s*$", lines[index])
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def exact_pins(path: Path) -> dict[str, str]:
    """Return normalized package names and exact versions from a requirements file."""

    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = EXACT_PIN_RE.match(line.strip())
        if not match:
            continue
        name = re.sub(r"[-_.]+", "-", match.group("name")).lower()
        pins[name] = match.group("version")
    return pins


class DependencyLockTests(unittest.TestCase):
    """Keep direct runtime and fuzz dependency declarations synchronized."""

    def test_direct_runtime_pins_match_lock(self) -> None:
        """Every exact direct pin must have the same exact locked version."""

        direct = exact_pins(ROOT / "requirements.txt")
        locked = exact_pins(ROOT / "requirements-lock.txt")
        drift = [
            (
                f"{name}: requirements.txt={version}, "
                f"requirements-lock.txt={locked.get(name, '<missing>')}"
            )
            for name, version in sorted(direct.items())
            if locked.get(name) != version
        ]

        self.assertTrue(direct, "requirements.txt contains no exact runtime pins")
        self.assertEqual(
            drift,
            [],
            "direct runtime dependency lock drift:\n" + "\n".join(drift),
        )

    def test_fuzz_input_and_hash_lock_use_current_atheris(self) -> None:
        """The fuzz input and lock must identify one exact, verified release."""

        fuzz_input = exact_pins(ROOT / "fuzz/requirements-fuzz.in")
        fuzz_lock_path = ROOT / "fuzz/requirements-fuzz.txt"
        fuzz_lock = exact_pins(fuzz_lock_path)
        hashes = set(SHA256_RE.findall(fuzz_lock_path.read_text(encoding="utf-8")))

        self.assertEqual(fuzz_input, {"atheris": "3.1.0"})
        self.assertEqual(fuzz_lock, fuzz_input)
        self.assertEqual(hashes, ATHERIS_HASHES)

    def test_fuzz_job_has_an_authoritative_runtime_bound(self) -> None:
        """The fuzz job must terminate even when instrumentation stalls."""

        job = workflow_job(ROOT / ".github/workflows/fuzz.yml", "fuzz")

        self.assertRegex(job, r"(?m)^    timeout-minutes: 15$")

    def test_fuzz_workflow_proves_both_supported_interpreters(self) -> None:
        """CI must install the exact lock on product and central-review Python."""

        job = workflow_job(
            ROOT / ".github/workflows/fuzz.yml", "fuzz-lock-compatibility"
        )
        matrix_match = re.search(r"python-version:\s*(\[[^\n]+\])", job)

        self.assertIsNotNone(matrix_match)
        self.assertEqual(literal_eval(matrix_match.group(1)), ["3.12", "3.14"])
        self.assertRegex(
            job,
            r"(?s)- name: Install the exact Atheris wheel\n"
            r"\s+run: \|\n(?P<command>.+?)(?=\n\s+- name:|\Z)",
        )
        install_command = re.search(
            r"(?s)- name: Install the exact Atheris wheel\n"
            r"\s+run: \|\n(?P<command>.+?)(?=\n\s+- name:|\Z)",
            job,
        ).group("command")
        self.assertIn("fuzz/requirements-fuzz.txt", install_command)
        self.assertIn("--require-hashes", install_command)
        self.assertIn("--only-binary=:all:", install_command)
        self.assertIn('python -c "import atheris;', install_command)
        self.assertIn("python -m pip check", install_command)
        self.assertNotIn("Atheris supports CPython 3.6 - 3.12", job)


if __name__ == "__main__":
    unittest.main()
