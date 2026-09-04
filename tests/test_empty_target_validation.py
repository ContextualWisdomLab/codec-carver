"""Focused contracts for required upload-field validation state."""

from __future__ import annotations

import unittest
from pathlib import Path


SOURCE_TEXT = (Path(__file__).resolve().parents[1] / "saas_web.py").read_text(
    encoding="utf-8"
)


class EmptyTargetValidationTests(unittest.TestCase):
    """Single and batch upload controls keep one consistent validity contract."""

    @staticmethod
    def _handler_between(start_marker: str, end_marker: str) -> str:
        """Return one JavaScript handler body from the web source text."""

        start = SOURCE_TEXT.index(start_marker)
        end = SOURCE_TEXT.index(end_marker, start)
        return SOURCE_TEXT[start:end]

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

        self.assertEqual(SOURCE_TEXT.count("if (this.value === '') {"), 2)

    def test_batch_controls_exist_before_batch_listener_initialization(self) -> None:
        """Batch listeners must not run before the batch form exists in the DOM."""

        batch_form = SOURCE_TEXT.index('id="shrink-batch-form"')
        batch_listener = SOURCE_TEXT.index(
            "document.getElementById('batch_preset_buttons_container').addEventListener"
        )
        self.assertLess(batch_form, batch_listener)

    def test_file_feedback_handles_change_invalid_and_cancel(self) -> None:
        """Picker cancellation and native invalid events reuse the visible feedback."""

        event_block = "['change', 'invalid', 'cancel'].forEach(eventName => {"
        self.assertIn(event_block, SOURCE_TEXT)
        self.assertIn(
            "fileInput.addEventListener(eventName, () => updateFileSizePreview(fileInput));",
            SOURCE_TEXT,
        )
        self.assertIn(
            "batchFileInput.addEventListener(eventName, () => updateBatchFilePreview(batchFileInput));",
            SOURCE_TEXT,
        )
        self.assertNotIn('onchange="updateFileSizePreview(this)"', SOURCE_TEXT)
        self.assertNotIn('onchange="updateBatchFilePreview(this)"', SOURCE_TEXT)

    def _assert_empty_branch(self, handler: str) -> None:
        """Assert one handler clears stale state before numeric validation."""

        empty_marker = "if (this.value === '') {"
        invalid_marker = "if (isNaN(val) || val <= 0) {"
        self.assertIn(empty_marker, handler)
        self.assertIn("preview.innerText = 'This field is required.';", handler)
        self.assertIn("preview.classList.add('required-star');", handler)
        self.assertIn("this.setCustomValidity('This field is required.');", handler)
        self.assertIn("this.setAttribute('aria-invalid', 'true');", handler)
        self.assertIn(
            "return;",
            handler[handler.index(empty_marker) : handler.index(invalid_marker)],
        )
        self.assertLess(handler.index(empty_marker), handler.index(invalid_marker))


if __name__ == "__main__":
    unittest.main()
