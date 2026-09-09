"""Focused contracts for required target-size validation feedback."""

from __future__ import annotations

import unittest
from pathlib import Path


SOURCE_TEXT = (Path(__file__).resolve().parents[1] / "saas_web.py").read_text(
    encoding="utf-8"
)


class EmptyTargetValidationTests(unittest.TestCase):
    """Both target-size inputs must expose the same missing-required state."""

    @staticmethod
    def _handler_between(start_marker: str, end_marker: str) -> str:
        """Return one JavaScript handler body from the web source text."""

        start = SOURCE_TEXT.index(start_marker)
        end = SOURCE_TEXT.index(end_marker, start)
        return SOURCE_TEXT[start:end]

    def test_single_target_empty_branch_keeps_required_feedback(self) -> None:
        """The single-file target handler keeps visible and semantic feedback."""

        handler = self._handler_between(
            "document.getElementById('target_bytes').addEventListener('input'",
            "document.getElementById('batch_target_bytes').addEventListener('input'",
        )
        self._assert_empty_branch(handler)

    def test_batch_target_empty_branch_keeps_required_feedback(self) -> None:
        """The batch target handler applies the identical required contract."""

        handler = self._handler_between(
            "document.getElementById('batch_target_bytes').addEventListener('input'",
            "document.getElementById('shrink-form').addEventListener('submit'",
        )
        self._assert_empty_branch(handler)

    def test_exactly_two_empty_target_branches_exist(self) -> None:
        """No unrelated input handler inherits the target-size special case."""

        self.assertEqual(SOURCE_TEXT.count("if (this.value === '') {"), 2)

    def _assert_empty_branch(self, handler: str) -> None:
        """Require stale-style cleanup followed by one explicit missing-value verdict."""

        cleanup_marker = "preview.classList.remove('required-star');"
        empty_marker = "if (this.value === '') {"
        invalid_marker = "if (isNaN(val) || val <= 0) {"
        self.assertIn(cleanup_marker, handler)
        self.assertIn(empty_marker, handler)
        self.assertLess(handler.index(cleanup_marker), handler.index(empty_marker))

        empty_start = handler.index(empty_marker)
        empty_end = handler.index("return;", empty_start)
        empty_branch = handler[empty_start:empty_end]
        self.assertIn("preview.innerText = 'This field is required.';", empty_branch)
        self.assertIn("preview.style.color = '';", empty_branch)
        self.assertIn("preview.classList.add('required-star');", empty_branch)
        self.assertIn("this.setCustomValidity('This field is required.');", empty_branch)
        self.assertIn("this.setAttribute('aria-invalid', 'true');", empty_branch)
        self.assertLess(handler.index(empty_marker), handler.index(invalid_marker))


if __name__ == "__main__":
    unittest.main()
