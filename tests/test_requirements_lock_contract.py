"""Regression contract for the Python 3.10 hashed dependency lock."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RequirementsLockContractTests(unittest.TestCase):
    """Keep conditional Python 3.10 runtime dependencies installable."""

    def test_python_310_exceptiongroup_is_hashed_in_lock(self) -> None:
        """Bind the supported Python 3.10 marker to the generated lock."""

        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lock = (ROOT / "requirements-lock.txt").read_text(encoding="utf-8")

        self.assertIn(
            'exceptiongroup==1.3.1; python_version < "3.11"', requirements
        )
        self.assertIn(
            'exceptiongroup==1.3.1 ; python_version < "3.11"', lock
        )
        self.assertIn("--python-version 3.10", lock)
        self.assertIn("--only-binary :all:", lock)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
