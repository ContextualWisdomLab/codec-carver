"""Regression tests for GitHub Actions checkout credential hardening."""

from pathlib import Path
import re
import unittest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATHS = (
    _REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml",
    _REPOSITORY_ROOT / ".github" / "workflows" / "fuzz.yml",
)
_CHECKOUT_STEP = re.compile(
    r"(?m)^\s*-\s+uses:\s+actions/checkout@[^\n]+\n"
    r"\s+with:\s*\n"
    r"\s+persist-credentials:\s*false\s*$"
)
_CHECKOUT_USE = re.compile(r"(?m)^\s*-\s+uses:\s+actions/checkout@")


class WorkflowSecurityTests(unittest.TestCase):
    """Protect repository workflows from persisting checkout credentials."""

    def test_every_checkout_disables_credential_persistence(self) -> None:
        """Require every checkout step to opt out of Git credential persistence."""
        for workflow_path in _WORKFLOW_PATHS:
            with self.subTest(workflow=workflow_path.name):
                workflow = workflow_path.read_text(encoding="utf-8")
                checkout_count = len(_CHECKOUT_USE.findall(workflow))
                self.assertGreater(checkout_count, 0)
                self.assertEqual(
                    len(_CHECKOUT_STEP.findall(workflow)),
                    checkout_count,
                    f"{workflow_path} must set persist-credentials: false "
                    "on every actions/checkout step",
                )


if __name__ == "__main__":
    unittest.main()
