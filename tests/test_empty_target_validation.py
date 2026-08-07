"""Focused contracts for clearing empty target-size validation state."""

from __future__ import annotations

import unittest

import saas_web


class EmptyTargetValidationTests(unittest.TestCase):
    """Both target-size inputs must clear stale custom validation when emptied."""

    @staticmethod
    def _handler_between(start_marker: str, end_marker: str) -> str:
        """Return one JavaScript handler body from the rendered HTML template."""

        html = saas_web.HTML_TEMPLATE
        start = html.index(start_marker)
        end = html.index(end_marker, start)
        return html[start:end]

    def test_single_target_empty_branch_clears_stale_state(self) -> None:
        """The single-file target handler clears preview and accessibility state."""

        handler = self._handler_between(
            "document.getElementById('target_bytes').addEventListener('input'",
            "document.getElementById('batch_target_bytes').addEventListener('input'",
        )
        self._assert_empty_branch(handler)

    def test_batch_target_empty_branch_clears_stale_state(self) -> None:
        """The batch target handler applies the identical empty-state contract."""

        handler = self._handler_between(
            "document.getElementById('batch_target_bytes').addEventListener('input'",
            "document.getElementById('shrink-form').addEventListener('submit'",
        )
        self._assert_empty_branch(handler)

    def test_exactly_two_empty_target_branches_exist(self) -> None:
        """No unrelated input handler inherits the target-size special case."""

        self.assertEqual(saas_web.HTML_TEMPLATE.count("if (this.value === '') {"), 2)

    def _assert_empty_branch(self, handler: str) -> None:
        """Assert one handler clears stale state before numeric validation."""

        empty_marker = "if (this.value === '') {"
        invalid_marker = "if (isNaN(val) || val <= 0) {"
        self.assertIn(empty_marker, handler)
        self.assertIn("preview.innerText = '';", handler)
        self.assertIn("this.setCustomValidity('');", handler)
        self.assertIn("this.removeAttribute('aria-invalid');", handler)
        self.assertIn("return;", handler[handler.index(empty_marker):handler.index(invalid_marker)])
        self.assertLess(handler.index(empty_marker), handler.index(invalid_marker))


if __name__ == "__main__":
    unittest.main()
