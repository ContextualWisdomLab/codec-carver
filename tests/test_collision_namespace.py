import os
import tempfile
import unittest
from pathlib import Path

import media_shrinker


class ResolveCollisionNamespaceTests(unittest.TestCase):
    """Regression tests for output-name occupancy semantics."""

    def test_dangling_symlink_consumes_name_when_overwrite_is_disabled(self) -> None:
        """A pathname entry is occupied even when its symlink target is absent."""
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are not supported on this platform")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "segment.flac"
            missing_target = root / "missing-target.flac"

            try:
                output.symlink_to(missing_target)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            self.assertTrue(output.is_symlink())
            self.assertFalse(output.exists())
            self.assertEqual(
                media_shrinker._resolve_collision(output, overwrite=False),
                root / "segment-1.flac",
            )


if __name__ == "__main__":
    unittest.main()
