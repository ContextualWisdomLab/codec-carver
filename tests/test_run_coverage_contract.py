"""Regression contracts for the repository-owned coverage entrypoint."""

from pathlib import Path
import unittest


class RunCoverageContractTest(unittest.TestCase):
    """Keep the coverage entrypoint fail-closed and single-pass."""

    def test_coverage_script_fails_closed_and_runs_suite_once(self):
        script = Path("run_coverage.sh").read_text(encoding="utf-8")

        self.assertIn("set -euo pipefail", script)
        self.assertEqual(script.count("coverage run"), 1)
        self.assertIn(
            "coverage run --source=saas_web -m unittest discover tests",
            script,
        )


if __name__ == "__main__":
    unittest.main()
