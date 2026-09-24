"""Focused contracts for protected-source path fast-path behavior."""

from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

from media_shrinker import MediaShrinkerError, _ensure_not_protected_source_path


class TestProtectedSourcePathFastPath(TestCase):
    """Keep the empty-set fast path observable without timing assumptions."""

    def test_empty_protected_sources_does_not_resolve_output(self) -> None:
        output = Mock(spec=Path)

        _ensure_not_protected_source_path(frozenset(), output)

        output.resolve.assert_not_called()

    def test_nonempty_protected_sources_resolves_output_once(self) -> None:
        output = Mock(spec=Path)
        resolved_output = Path("/tmp/codec-carver-output")
        output.resolve.return_value = resolved_output

        _ensure_not_protected_source_path(
            frozenset({Path("/tmp/another-protected-source")}), output
        )

        output.resolve.assert_called_once_with()

    def test_matching_protected_source_still_fails_closed(self) -> None:
        output = Mock(spec=Path)
        resolved_output = Path("/tmp/codec-carver-protected-source")
        output.resolve.return_value = resolved_output

        with self.assertRaises(MediaShrinkerError):
            _ensure_not_protected_source_path(frozenset({resolved_output}), output)

        output.resolve.assert_called_once_with()
