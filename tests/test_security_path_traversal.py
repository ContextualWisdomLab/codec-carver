import unittest
from pathlib import Path
from media_shrinker import convert_file

class TestSecurityPathTraversal(unittest.TestCase):
    def test_convert_file_raises_value_error_if_source_not_in_root(self):
        source = Path("/tmp/outside.mp4")
        root = Path("/tmp/myroot")
        with self.assertRaises(ValueError):
            convert_file(source, root=root, output_dir=Path("/tmp/out"))

if __name__ == '__main__':
    unittest.main()
