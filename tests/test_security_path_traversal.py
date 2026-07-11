import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from media_shrinker import MediaShrinkerError, convert_file


class TestSecurityPathTraversal(unittest.TestCase):
    def test_convert_file_rejects_source_not_in_root(self):
        source = Path("/tmp/outside.mp4")
        root = Path("/tmp/myroot")
        with self.assertRaisesRegex(
            MediaShrinkerError, "outside the permitted root directory"
        ) as ctx:
            convert_file(source, root=root, output_dir=Path("/tmp/out"))
        self.assertNotIn("/tmp/myroot", str(ctx.exception))
        self.assertNotIn("/tmp/outside.mp4", str(ctx.exception))

    def test_convert_file_rejects_symlink_escape_from_root(self):
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            outside = base / "outside.mp4"
            source = root / "linked.mp4"
            root.mkdir()
            outside.write_bytes(b"not a real media file")
            try:
                source.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(
                MediaShrinkerError, "outside the permitted root directory"
            ):
                convert_file(source, root=root, output_dir=base / "out")

if __name__ == '__main__':
    unittest.main()
