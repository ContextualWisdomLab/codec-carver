#!/usr/bin/env python3
"""Fail closed when an hourly OpenCode change exceeds its bounded contract."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from pathlib import Path


PROTECTED_PATH = re.compile(
    r"^(?:\.github/workflows/|\.github/actions/|\.github/opencode/|"
    r"\.github/scripts/|AGENTS\.md$|CLAUDE\.md$|SECURITY\.md$|"
    r"opencode\.jsonc$|\.env(?:$|\.)|pyproject\.toml$|"
    r"requirements[^/]*\.txt$|.*lock[^/]*$|CHANGELOG\.md$)"
)


def _git_lines(*arguments: str) -> list[str]:
    """Return non-empty UTF-8 lines from a git command."""
    completed = subprocess.run(
        ["git", *arguments], check=True, capture_output=True, text=True
    )
    return [line for line in completed.stdout.splitlines() if line]


def _changed_files() -> list[str]:
    """Return tracked and untracked changed files in deterministic order."""
    paths = set(_git_lines("diff", "--name-only"))
    paths.update(_git_lines("ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def _changed_line_count() -> int:
    """Count added and deleted lines in the tracked working-tree diff."""
    total = 0
    for line in _git_lines("diff", "--numstat"):
        added, deleted, _ = line.split("\t", 2)
        if added.isdigit():
            total += int(added)
        if deleted.isdigit():
            total += int(deleted)
    return total


def _missing_docstrings(paths: list[str]) -> list[str]:
    """Return production modules and callables that lack docstrings."""
    missing: list[str] = []
    for raw_path in paths:
        if not raw_path.endswith(".py") or raw_path.startswith(("tests/", "fuzz/", "scripts/")):
            continue
        path = Path(raw_path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if ast.get_docstring(tree, clean=False) is None:
            missing.append(f"{path}: module")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if ast.get_docstring(node, clean=False) is None:
                    missing.append(f"{path}:{node.lineno}: {node.name}")
    return missing


def validate(max_files: int, max_lines: int) -> list[str]:
    """Validate scope and return the changed paths when the contract holds."""
    changed = _changed_files()
    if len(changed) > max_files:
        raise SystemExit(f"changed-file budget exceeded: {len(changed)} > {max_files}")
    deleted = _git_lines("diff", "--diff-filter=D", "--name-only")
    if deleted:
        raise SystemExit("hourly product-gap runs may not delete files: " + ", ".join(deleted))
    changed_lines = _changed_line_count()
    if changed_lines > max_lines:
        raise SystemExit(f"changed-line budget exceeded: {changed_lines} > {max_lines}")
    protected = [path for path in changed if PROTECTED_PATH.search(path)]
    if protected:
        raise SystemExit("protected paths changed: " + ", ".join(protected))
    missing = _missing_docstrings(changed)
    if missing:
        raise SystemExit("missing production docstrings:\n" + "\n".join(missing))
    return changed


def main() -> int:
    """Run the bounded-scope validator and print changed paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--max-lines", type=int, default=2500)
    arguments = parser.parse_args()
    if arguments.max_files <= 0 or arguments.max_lines <= 0:
        parser.error("budgets must be positive")
    for path in validate(arguments.max_files, arguments.max_lines):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
