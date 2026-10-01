"""Contracts for repository dependency security manifests."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_MANIFESTS = (
    REPOSITORY_ROOT / "requirements.txt",
    REPOSITORY_ROOT / "requirements-lock.txt",
    REPOSITORY_ROOT / "pyproject.toml",
)


class DependencySecurityContractTests(unittest.TestCase):
    """Keep removed vulnerable dependency families out of every manifest."""

    def test_dependency_manifests_exclude_obsolete_httpx2(self) -> None:
        """Reject the vulnerable, unused httpx2 compatibility fork."""

        for dependency_manifest in DEPENDENCY_MANIFESTS:
            with self.subTest(dependency_manifest=dependency_manifest.name):
                manifest_text = dependency_manifest.read_text(encoding="utf-8")
                self.assertNotIn("httpx2", manifest_text.lower())


if __name__ == "__main__":
    unittest.main()
