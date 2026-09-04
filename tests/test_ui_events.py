import unittest
from pathlib import Path
import re

class TestUIEvents(unittest.TestCase):
    def setUp(self):
        root_dir = Path(__file__).parent.parent
        with open(root_dir / "saas_web.py", "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_dom_content_loaded(self):
        self.assertIn("document.addEventListener('DOMContentLoaded'", self.content)

    def test_no_inline_onchange(self):
        match_file = re.search(r'<input[^>]+id="file"[^>]*>', self.content)
        self.assertIsNotNone(match_file)
        self.assertNotIn('onchange=', match_file.group(0))

        match_batch = re.search(r'<input[^>]+id="batch_files"[^>]*>', self.content)
        self.assertIsNotNone(match_batch)
        self.assertNotIn('onchange=', match_batch.group(0))

    def test_event_listeners_added(self):
        self.assertIn("['change', 'invalid', 'cancel'].forEach(event => {", self.content)


if __name__ == '__main__':
    unittest.main()
