"""Focused contracts for required target-size validation state cleanup."""

from __future__ import annotations

import unittest
from pathlib import Path


SOURCE_TEXT = (Path(__file__).resolve().parents[1] / "saas_web.py").read_text(
    encoding="utf-8"
)


class EmptyTargetValidationTests(unittest.TestCase):
    """Both target-size inputs must keep required validation state internally consistent."""

    @staticmethod
    def _handler_between(start_marker: str, end_marker: str) -> str:
        """Return one JavaScript handler body from the web source text."""

        start = SOURCE_TEXT.index(start_marker)
        end = SOURCE_TEXT.index(end_marker, start)
        return SOURCE_TEXT[start:end]

    def test_single_target_empty_branch_clears_stale_state(self) -> None:
        """The single-file target handler resets stale styling before validating."""

        handler = self._handler_between(
            "document.getElementById('target_bytes').addEventListener('input'",
            "document.getElementById('batch_target_bytes').addEventListener('input'",
        )
        self._assert_empty_branch(handler)

    def test_batch_target_empty_branch_clears_stale_state(self) -> None:
        """The batch target handler applies the identical cleanup contract."""

        handler = self._handler_between(
            "document.getElementById('batch_target_bytes').addEventListener('input'",
            "document.getElementById('shrink-form').addEventListener('submit'",
        )
        self._assert_empty_branch(handler)

    def test_exactly_two_empty_target_branches_exist(self) -> None:
        """No unrelated input handler inherits the target-size special case."""

        self.assertEqual(SOURCE_TEXT.count("if (this.value === '') {"), 2)

    def _assert_empty_branch(self, handler: str) -> None:
        """Assert one handler clears stale required styling before revalidation."""

        empty_marker = "if (this.value === '') {"
        invalid_marker = "if (isNaN(val) || val <= 0) {"
        self.assertIn(empty_marker, handler)
        cleanup_marker = "preview.classList.remove('required-star');"
        self.assertIn(cleanup_marker, handler)
        self.assertLess(handler.index(cleanup_marker), handler.index(empty_marker))
        self.assertIn("preview.innerText = 'This field is required.';", handler)
        self.assertIn("this.setCustomValidity('This field is required.');", handler)
        self.assertIn("this.setAttribute('aria-invalid', 'true');", handler)
        self.assertIn(
            "return;",
            handler[handler.index(empty_marker) : handler.index(invalid_marker)],
        )
        self.assertLess(handler.index(empty_marker), handler.index(invalid_marker))


if __name__ == "__main__":
    unittest.main()
