from importlib.metadata import version
from pathlib import Path
import re
import unittest


class DependencyLockContractTests(unittest.TestCase):
    def test_installed_httpx2_matches_declared_runtime_pin(self) -> None:
        """Keep the hash-locked install aligned with the runtime dependency declaration."""
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        match = re.search(r"^httpx2==(\S+)$", requirements, re.MULTILINE)
        self.assertIsNotNone(match, "requirements.txt must pin httpx2 exactly")

        assert match is not None
        declared_version = match.group(1)
        self.assertEqual(version("httpx2"), declared_version)
