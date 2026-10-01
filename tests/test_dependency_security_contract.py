"""Security floors for dependencies with repository-wide scan findings."""

from pathlib import Path
import re


def _pinned_version(path: str, package_name: str) -> tuple[int, ...]:
    """Return a package pin from a requirements file as integers."""
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(rf"(?m)^{re.escape(package_name)}==([0-9.]+)", text)
    assert match is not None, f"{package_name} must be pinned in {path}"
    return tuple(int(part) for part in match.group(1).split("."))


def test_httpx2_decompression_fix_is_pinned_in_source_and_lock() -> None:
    """Keep the CVE-2026-84382 fix in both source and generated lock."""
    assert _pinned_version("requirements.txt", "httpx2") >= (2, 12, 0)
    assert _pinned_version("requirements-lock.txt", "httpx2") >= (2, 12, 0)
