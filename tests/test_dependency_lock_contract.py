from importlib.metadata import version
from pathlib import Path
import re


def test_installed_httpx2_matches_declared_runtime_pin() -> None:
    """Keep the hash-locked install aligned with the runtime dependency declaration."""
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    match = re.search(r"^httpx2==(\S+)$", requirements, re.MULTILINE)
    assert match is not None, "requirements.txt must pin httpx2 exactly"

    declared_version = match.group(1)
    assert version("httpx2") == declared_version
