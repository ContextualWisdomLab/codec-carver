import errno
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import media_shrinker


class NoClobberPublishTests(unittest.TestCase):
    def test_overwrite_false_preserves_entry_created_at_publish_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.wav"
            output = root / "output.flac"
            source.write_bytes(b"source")
            plan = media_shrinker.ConversionPlan(
                strategy="test",
                input_path=source,
                output_path=output,
                ffmpeg_args=["-y", "-i", str(source), str(output)],
            )

            def publish_collision(_source, destination, *args, **kwargs):
                Path(destination).write_bytes(b"competing-writer")
                raise FileExistsError(errno.EEXIST, "destination appeared during publish")

            with patch(
                "media_shrinker._run_media_tool",
                return_value=SimpleNamespace(returncode=0, stderr=""),
            ):
                with patch("media_shrinker.os.link", side_effect=publish_collision):
                    with self.assertRaises(FileExistsError):
                        media_shrinker._execute_plan(
                            plan,
                            source,
                            output,
                            ffmpeg_path="ffmpeg",
                            overwrite=False,
                        )

            self.assertEqual(output.read_bytes(), b"competing-writer")


if __name__ == "__main__":
    unittest.main()
