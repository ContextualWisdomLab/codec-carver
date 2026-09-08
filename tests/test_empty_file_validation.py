"""Contracts for required file-input feedback and batch listener readiness."""

from __future__ import annotations

import unittest
from pathlib import Path


SOURCE_TEXT = (Path(__file__).resolve().parents[1] / "saas_web.py").read_text(
    encoding="utf-8"
)


class EmptyFileValidationTests(unittest.TestCase):
    """Single and batch file inputs must expose the same missing-required state."""

    @staticmethod
    def _handler_between(start_marker: str, end_marker: str) -> str:
        """Return one JavaScript function body from the web source text."""

        start = SOURCE_TEXT.index(start_marker)
        end = SOURCE_TEXT.index(end_marker, start)
        return SOURCE_TEXT[start:end]

    def test_single_file_empty_state_is_explicit(self) -> None:
        """Clearing the single-file control keeps visible and semantic feedback."""

        handler = self._handler_between(
            "function updateFileSizePreview(input) {",
            "document.getElementById('target_bytes').addEventListener('input'",
        )
        self._assert_required_empty_state(handler, "if (!file) {")

    def test_batch_file_empty_state_is_explicit(self) -> None:
        """Clearing the batch-file control follows the same required contract."""

        handler = self._handler_between(
            "function updateBatchFilePreview(input) {",
            "document.getElementById('shrink-batch-form').addEventListener('submit'",
        )
        self._assert_required_empty_state(
            handler,
            "if (!files || files.length === 0) {",
        )

    def test_batch_controls_exist_before_script_binds_listeners(self) -> None:
        """The inline script must not dereference batch controls before they exist."""

        batch_form = SOURCE_TEXT.index('id="shrink-batch-form"')
        script = SOURCE_TEXT.index("<script>", batch_form)
        batch_listener = SOURCE_TEXT.index(
            "document.getElementById('batch_preset_buttons_container').addEventListener",
            script,
        )
        self.assertLess(batch_form, script)
        self.assertLess(script, batch_listener)

    def _assert_required_empty_state(self, handler: str, empty_marker: str) -> None:
        """Require stale-error cleanup followed by one explicit missing-file verdict."""

        cleanup_marker = "preview.classList.remove('required-star');"
        self.assertIn(cleanup_marker, handler)
        self.assertLess(handler.index(cleanup_marker), handler.index(empty_marker))

        empty_start = handler.index(empty_marker)
        empty_end = handler.index("return;", empty_start)
        empty_branch = handler[empty_start:empty_end]
        self.assertIn("preview.innerText = 'This field is required.';", empty_branch)
        self.assertIn("preview.style.color = '';", empty_branch)
        self.assertIn("preview.classList.add('required-star');", empty_branch)
        self.assertIn("input.setCustomValidity('This field is required.');", empty_branch)
        self.assertIn("input.setAttribute('aria-invalid', 'true');", empty_branch)


if __name__ == "__main__":
    unittest.main()
