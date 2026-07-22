"""Security regression tests for the persistent macOS MLX runtime bootstrap."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap_macos_gpu_runtime.sh"
LOCK_FILE = REPO_ROOT / "requirements-macos-mlx-lock.txt"


class MacosGpuBootstrapTests(unittest.TestCase):
    @staticmethod
    def _run_bootstrap(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """Run the Bash program without depending on its executable mode bit."""

        return subprocess.run(
            ["/bin/bash", str(BOOTSTRAP), *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_bootstrap_uses_only_hash_locked_remote_dependencies(self) -> None:
        script = BOOTSTRAP.read_text(encoding="utf-8")

        self.assertIn('LOCK_FILE="$REPO_ROOT/requirements-macos-mlx-lock.txt"', script)
        self.assertIn("--require-hashes", script)
        self.assertIn("--only-binary :all:", script)
        self.assertIn('--requirements "$LOCK_FILE"', script)
        self.assertNotIn("--editable", script)
        self.assertIn('[[ "$("$UNAME_BIN" -m)" == "arm64" ]]', script)
        self.assertIn('cd -- "$RUNTIME_DIR"', script)
        self.assertIn('--python "./bin/python"', script)
        self.assertIn('secure_directory_identity . "runtime directory"', script)
        self.assertIn('PATH="/usr/bin:/bin:/usr/sbin:/sbin"', script)
        self.assertIn('DIRNAME_BIN="/usr/bin/dirname"', script)
        self.assertIn('UV_BIN="/opt/homebrew/bin/uv"', script)
        self.assertIn('UV_SNAPSHOT="$("$MKTEMP_BIN"', script)
        self.assertIn('sha256_file "$UV_SNAPSHOT"', script)
        self.assertNotIn("command -v", script)

    def test_every_locked_requirement_is_exact_and_hashed(self) -> None:
        lock = LOCK_FILE.read_text(encoding="utf-8")
        blocks = re.split(r"(?m)(?=^[A-Za-z0-9_.-]+==)", lock)
        requirements = [
            block for block in blocks if re.match(r"^[A-Za-z0-9_.-]+==", block)
        ]

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

    def test_hostile_path_cannot_hijack_bootstrap_help(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "marker"
            hostile_dirname = root / "dirname"
            hostile_dirname.write_text(
                f'#!/bin/sh\nprintf owned > {str(marker)!r}\nexec /usr/bin/dirname "$@"\n',
                encoding="utf-8",
            )
            hostile_dirname.chmod(0o700)
            inherited_path = os.environ.get("PATH")
            hostile_path = str(root) if not inherited_path else f"{root}:{inherited_path}"
            completed = self._run_bootstrap(
                "--help",
                env={**os.environ, "PATH": hostile_path},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS bootstrap runtime test")
    def test_bootstrap_rejects_broad_symlinked_and_swapped_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            fake_bin = root / "bin"
            escape = root / "escape"
            home.mkdir()
            fake_bin.mkdir()
            escape.mkdir()
            trusted_root = home / "Library" / "Caches" / "codec-carver" / "venvs"
            trusted_root.mkdir(parents=True)

            (fake_bin / "uname").write_text(
                '#!/bin/sh\n[ "$1" = -s ] && echo Darwin || echo arm64\n',
                encoding="utf-8",
            )
            (fake_bin / "xattr").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            (fake_bin / "uv").write_text(
                """#!/bin/bash
set -e
if [[ "$1" == "venv" ]]; then
    if [[ -n "${RACE_RUNTIME:-}" ]]; then
        mv "$RACE_RUNTIME" "$RACE_RUNTIME.moved"
        ln -s "$RACE_TARGET" "$RACE_RUNTIME"
    fi
    mkdir -p ./bin
    : > ./bin/python
    chmod +x ./bin/python
fi
""",
                encoding="utf-8",
            )
            for executable in fake_bin.iterdir():
                executable.chmod(0o700)
            uv_sha256 = hashlib.sha256((fake_bin / "uv").read_bytes()).hexdigest()

            inherited_path = os.environ.get("PATH")
            test_path = (
                str(fake_bin)
                if not inherited_path
                else f"{fake_bin}:{inherited_path}"
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": test_path,
            }
            uv_options = [
                "--uv-bin",
                str(fake_bin / "uv"),
                "--uv-sha256",
                uv_sha256,
            ]

            broad = self._run_bootstrap(
                "--runtime-dir",
                f"{home}/",
                *uv_options,
                env=env,
            )
            self.assertNotEqual(broad.returncode, 0)
            self.assertIn("runtime path is too broad", broad.stderr)

            symlink_runtime = trusted_root / "linked"
            symlink_runtime.symlink_to(Path("/"), target_is_directory=True)
            linked = self._run_bootstrap(
                "--runtime-dir",
                str(symlink_runtime),
                *uv_options,
                env=env,
            )
            self.assertNotEqual(linked.returncode, 0)
            self.assertIn("runtime path must be a real directory", linked.stderr)

            raced_runtime = trusted_root / "raced"
            raced_env = {
                **env,
                "RACE_RUNTIME": str(raced_runtime),
                "RACE_TARGET": str(escape),
            }
            raced = self._run_bootstrap(
                "--runtime-dir",
                str(raced_runtime),
                *uv_options,
                env=raced_env,
            )
            self.assertNotEqual(raced.returncode, 0)
            self.assertIn("runtime directory path changed", raced.stderr)
            self.assertFalse((escape / "bin" / "python").exists())


if __name__ == "__main__":
    unittest.main()
