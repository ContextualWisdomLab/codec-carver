"""Focused contracts for target-size validation state and error meaning."""

from __future__ import annotations

import unittest
from pathlib import Path


SOURCE_TEXT = (Path(__file__).resolve().parents[1] / "saas_web.py").read_text(
    encoding="utf-8"
)


class EmptyTargetValidationTests(unittest.TestCase):
    """Both target-size inputs distinguish clear, bad-input, and range states."""

    @staticmethod
    def _handler_between(start_marker: str, end_marker: str) -> str:
        """Return one JavaScript handler body from the web source text."""

        start = SOURCE_TEXT.index(start_marker)
        end = SOURCE_TEXT.index(end_marker, start)
        return SOURCE_TEXT[start:end]

    def test_single_target_validation_states_are_distinct(self) -> None:
        """The single-file target reports malformed numeric input separately."""

        handler = self._handler_between(
            "document.getElementById('target_bytes').addEventListener('input'",
            "document.getElementById('batch_target_bytes').addEventListener('input'",
        )
        self._assert_validation_states(handler)

    def test_batch_target_validation_states_are_distinct(self) -> None:
        """The batch target applies the identical validation-state contract."""

        handler = self._handler_between(
            "document.getElementById('batch_target_bytes').addEventListener('input'",
            "document.getElementById('shrink-form').addEventListener('submit'",
        )
        self._assert_validation_states(handler)

    def test_exactly_two_clear_target_branches_exist(self) -> None:
        """No unrelated input handler inherits the target-size special case."""

        self.assertEqual(
            SOURCE_TEXT.count("if (this.value === '' && !this.validity.badInput) {"),
            2,
        )

    def _assert_validation_states(self, handler: str) -> None:
        """Require clear, malformed, and non-positive values to remain distinguishable."""

        empty_marker = "if (this.value === '' && !this.validity.badInput) {"
        bad_input_marker = "if (this.validity.badInput) {"
        range_marker = "if (isNaN(val) || val <= 0) {"

        self.assertIn(empty_marker, handler)
        self.assertIn("preview.innerText = '';", handler)
        self.assertIn("this.setCustomValidity('');", handler)
        self.assertIn("this.removeAttribute('aria-invalid');", handler)
        self.assertIn(
            "return;",
            handler[handler.index(empty_marker) : handler.index(range_marker)],
        )

        self.assertIn(bad_input_marker, handler)
        bad_input = handler[
            handler.index(bad_input_marker) : handler.index(range_marker)
        ]
        self.assertIn("Enter a valid number greater than 0.", bad_input)
        self.assertIn("this.setAttribute('aria-invalid', 'true');", bad_input)
        self.assertIn("return;", bad_input)

        range_branch = handler[handler.index(range_marker) :]
        self.assertIn("Must be greater than 0.", range_branch)
        self.assertIn("this.setAttribute('aria-invalid', 'true');", range_branch)

        self.assertLess(handler.index(empty_marker), handler.index(bad_input_marker))
        self.assertLess(handler.index(bad_input_marker), handler.index(range_marker))


if __name__ == "__main__":
    unittest.main()
