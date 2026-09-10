import os
import tempfile
import unittest
from pathlib import Path

import media_shrinker


class CollisionNamespaceTests(unittest.TestCase):
    def test_dangling_symlink_occupies_output_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            occupied = root / "segment.flac"
            try:
                os.symlink(root / "missing-target.flac", occupied)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            resolved = media_shrinker._resolve_collision(occupied, overwrite=False)

            self.assertEqual(resolved, root / "segment-1.flac")
            self.assertTrue(occupied.is_symlink())
            self.assertFalse(occupied.exists())


if __name__ == "__main__":
    unittest.main()
