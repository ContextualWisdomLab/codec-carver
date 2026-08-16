"""Dependency-free contracts for the embedded SaaS browser UI."""

import unittest
from pathlib import Path


SOURCE_TEXT = (Path(__file__).resolve().parents[1] / "saas_web.py").read_text(
    encoding="utf-8"
)


class TestSaasUiContract(unittest.TestCase):
    """Keep DOM registration and nested-control handling safe."""

    def test_drop_zone_registration_waits_for_complete_dom(self):
        """Batch controls must exist before any listener looks them up."""
        self.assertIn("window.addEventListener('DOMContentLoaded'", SOURCE_TEXT)
        self.assertLess(
            SOURCE_TEXT.index("window.addEventListener('DOMContentLoaded'"),
            SOURCE_TEXT.index(
                "document.getElementById('batch_preset_buttons_container')"
            ),
        )
        self.assertIn("window.updateFileSizePreview = function(input)", SOURCE_TEXT)

    def test_nested_interactive_elements_do_not_open_file_picker_twice(self):
        """A child span inside a label remains part of that interactive label."""
        self.assertEqual(
            SOURCE_TEXT.count("e.target.closest('input, button, label')"), 2
        )


if __name__ == "__main__":
    unittest.main()
