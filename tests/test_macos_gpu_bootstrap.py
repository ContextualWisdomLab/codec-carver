"""Security regression tests for the persistent macOS MLX runtime bootstrap."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap_macos_gpu_runtime.sh"
LOCK_FILE = REPO_ROOT / "requirements-macos-mlx-lock.txt"


class MacosGpuBootstrapTests(unittest.TestCase):
    def test_bootstrap_uses_only_hash_locked_remote_dependencies(self) -> None:
        script = BOOTSTRAP.read_text(encoding="utf-8")

        self.assertIn('LOCK_FILE="$REPO_ROOT/requirements-macos-mlx-lock.txt"', script)
        self.assertIn("--require-hashes", script)
        self.assertIn("--only-binary :all:", script)
        self.assertIn('--requirements "$LOCK_FILE"', script)
        self.assertNotIn("--editable", script)
        self.assertIn('[[ "$(uname -m)" == "arm64" ]]', script)

    def test_every_locked_requirement_is_exact_and_hashed(self) -> None:
        lock = LOCK_FILE.read_text(encoding="utf-8")
        blocks = re.split(r"(?m)(?=^[A-Za-z0-9_.-]+==)", lock)
        requirements = [block for block in blocks if re.match(r"^[A-Za-z0-9_.-]+==", block)]

        self.assertGreater(len(requirements), 50)
        for requirement in requirements:
            first_line = requirement.splitlines()[0]
            with self.subTest(requirement=first_line):
                name_and_version, continuation = first_line.rsplit(" ", 1)
                self.assertRegex(name_and_version, r"^[A-Za-z0-9_.-]+==\S+$")
                self.assertEqual(continuation, "\\")
                self.assertIn("--hash=sha256:", requirement)

    def test_lock_includes_pinned_mlx_stack(self) -> None:
        lock = LOCK_FILE.read_text(encoding="utf-8")

        for requirement in (
            "huggingface-hub==1.23.0",
            "mlx-vlm==0.6.4",
            "mlx-whisper==0.4.3",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, lock)


if __name__ == "__main__":
    unittest.main()
