"""Contract tests for the repo-managed Cloud Agent environment."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_JSON = ROOT / ".cursor" / "environment.json"
INSTALL_SH = ROOT / ".cursor" / "install.sh"
START_SH = ROOT / ".cursor" / "start.sh"


class CloudAgentEnvironmentTests(unittest.TestCase):
    """Keep install/start scripts aligned with CI and the public env schema."""

    def test_environment_json_declares_install_start_and_web_port(self) -> None:
        """Require the fields Cloud Agents need to boot the SaaS UI."""

        payload = json.loads(ENVIRONMENT_JSON.read_text(encoding="utf-8"))
        self.assertNotIn("$schema", payload)
        self.assertEqual(payload["name"], "Codec Carver")
        self.assertEqual(payload["install"], "bash .cursor/install.sh")
        self.assertEqual(payload["start"], "bash .cursor/start.sh")
        self.assertEqual(payload["ports"], [{"name": "web", "port": 8000}])

    def test_install_and_start_scripts_are_valid_bash(self) -> None:
        """Reject a script that `bash -n` cannot parse before an agent runs it."""

        for script in (INSTALL_SH, START_SH):
            with self.subTest(script=script.name):
                completed = subprocess.run(
                    ["bash", "-n", str(script)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_install_pins_repo_root_and_hash_locked_python(self) -> None:
        """Install must cd to the tree and follow the CI pip contract."""

        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn('cd "$(dirname "$0")/.."', text)
        self.assertIn("--require-hashes -r requirements-lock.txt", text)
        self.assertIn("--no-index --no-deps --no-build-isolation -e .", text)
        self.assertIn("-r requirements-dev.txt", text)
        self.assertNotIn("|| true", text)
        self.assertIn("rustup component add rustfmt", text)
        self.assertIn("cargo build --release --manifest-path rust-core/Cargo.toml", text)

    def test_start_waits_for_health_and_fails_if_worker_dies(self) -> None:
        """Start must probe /health and exit non-zero when uvicorn dies."""

        text = START_SH.read_text(encoding="utf-8")
        self.assertIn('cd "$(dirname "$0")/.."', text)
        self.assertIn("http://127.0.0.1:8000/health", text)
        self.assertIn("uvicorn saas_web:app --host 0.0.0.0 --port 8000", text)
        self.assertIn("uvicorn exited before becoming ready", text)
        self.assertIn("uvicorn did not become ready", text)
        self.assertIn("kill -0", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
