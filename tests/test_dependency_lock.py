"""Regression tests for dependency-lock consistency and interpreter support."""

from __future__ import annotations

import re
import unittest
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

    def test_fuzz_workflow_proves_both_supported_interpreters(self) -> None:
        """CI must install the exact lock on product and central-review Python."""

        workflow = (ROOT / ".github/workflows/fuzz.yml").read_text(encoding="utf-8")

        self.assertIn("fuzz-lock-compatibility:", workflow)
        self.assertIn('python-version: ["3.12", "3.14"]', workflow)
        self.assertIn("--require-hashes --only-binary=:all:", workflow)
        self.assertIn("python -c \"import atheris;", workflow)
        self.assertNotIn("Atheris supports CPython 3.6 - 3.12", workflow)


if __name__ == "__main__":
    unittest.main()
