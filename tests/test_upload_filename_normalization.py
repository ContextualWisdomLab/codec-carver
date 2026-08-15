"""Cross-platform upload filename normalization regressions.

These tests lock the public upload boundary to one canonical basename helper and
verify that every converter source remains inside its request-scoped root.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi import BackgroundTasks

    import saas_web

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(
    _HAS_FASTAPI,
    "fastapi not installed (optional integration dependency)",
)
class UploadFilenameNormalizationTests(unittest.TestCase):
    """Keep Windows and POSIX upload names canonical and workspace-contained."""

    def test_canonical_basename_handles_both_separator_families_and_fallbacks(self):
        """One helper normalizes client paths and rejects empty relative names."""
        cases = {
            r"..\..\etc\passwd": "passwd",
            "../../etc/passwd": "passwd",
            r"C:\recordings\meeting.wav": "meeting.wav",
            "/tmp/recordings/meeting.wav": "meeting.wav",
            "meeting.wav": "meeting.wav",
            "": "upload.tmp",
            ".": "upload.tmp",
            "..": "upload.tmp",
        }

        for raw_name, expected in cases.items():
            with self.subTest(raw_name=raw_name):
                self.assertEqual(
                    saas_web._safe_upload_basename(raw_name),
                    expected,
                )

    @patch("saas_web.media_shrinker.convert_file")
    def test_single_upload_uses_canonical_contained_source(self, mock_convert_file):
        """The single-upload converter receives the basename inside its input root."""
        with tempfile.TemporaryDirectory() as output_directory:
            output_path = Path(output_directory) / "output.flac"
            output_path.write_bytes(b"audio")
            mock_convert_file.return_value = [SimpleNamespace(output_path=output_path)]

            response = saas_web.shrink_media(
                BackgroundTasks(),
                file=SimpleNamespace(
                    filename=r"..\..\etc\passwd",
                    content_type="audio/wav",
                    file=io.BytesIO(b"audio"),
                ),
                target_bytes=10_000,
            )

            call = mock_convert_file.call_args.kwargs
            source = Path(call["source"])
            root = Path(call["root"])
            try:
                self.assertEqual(Path(response.path), output_path)
                self.assertEqual(source.name, "passwd")
                self.assertTrue(source.resolve().is_relative_to(root.resolve()))
                self.assertEqual(source.parent.resolve(), root.resolve())
            finally:
                saas_web.cleanup_temp_dir(source.parent.parent)

    @patch("saas_web.media_shrinker.convert_file")
    def test_batch_upload_checks_every_converter_source(self, mock_convert_file):
        """Every batch item is canonicalized and contained before conversion."""

        def fake_convert(source, root, output_dir, target_bytes):
            self.assertEqual(target_bytes, 10_000)
            output_path = Path(output_dir) / f"{Path(source).stem}.flac"
            output_path.write_bytes(b"shrunk")
            return [SimpleNamespace(output_path=output_path)]

        mock_convert_file.side_effect = fake_convert
        response = saas_web.shrink_media_batch(
            BackgroundTasks(),
            files=[
                SimpleNamespace(
                    filename=r"..\..\etc\passwd",
                    content_type="audio/wav",
                    file=io.BytesIO(b"first"),
                ),
                SimpleNamespace(
                    filename="folder/meeting.wav",
                    content_type="audio/wav",
                    file=io.BytesIO(b"second"),
                ),
            ],
            target_bytes=10_000,
        )

        archive_path = Path(response.path)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                manifest = json.loads(archive.read("results.json"))
            self.assertEqual(
                [item["filename"] for item in manifest["results"]],
                ["passwd", "meeting.wav"],
            )
            self.assertEqual(mock_convert_file.call_count, 2)
            observed_names = []
            for call in mock_convert_file.call_args_list:
                source = Path(call.kwargs["source"])
                root = Path(call.kwargs["root"])
                observed_names.append(source.name)
                self.assertTrue(source.resolve().is_relative_to(root.resolve()))
                self.assertEqual(source.parent.resolve(), root.resolve())
            self.assertEqual(observed_names, ["passwd", "meeting.wav"])
        finally:
            saas_web.cleanup_temp_dir(archive_path.parent)


if __name__ == "__main__":
    unittest.main()
