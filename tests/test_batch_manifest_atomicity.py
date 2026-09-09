"""Batch archive manifest invariants for multi-segment conversion results."""

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
    from fastapi.testclient import TestClient

    import saas_web
    from saas_web import app

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(
    _HAS_FASTAPI, "fastapi not installed (optional integration dependency)"
)
class BatchManifestAtomicityTests(unittest.TestCase):
    """One upload entry must not report or archive a partial segment set as success."""

    def setUp(self) -> None:
        """Create the API client used by each batch request."""

        self.client = TestClient(app)

    @staticmethod
    def _read_archive(response):
        """Return archive member names and parsed batch manifest."""

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = sorted(archive.namelist())
            manifest = json.loads(archive.read("results.json"))
        return names, manifest

    @patch("saas_web.media_shrinker.convert_file")
    def test_invalid_later_segment_does_not_publish_partial_success(
        self, mock_convert_file
    ) -> None:
        """A later invalid segment makes the whole upload entry fail atomically."""

        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside.flac"
            outside.write_bytes(b"outside")

            def convert(source, root, output_dir, target_bytes):
                del source, root, target_bytes
                inside = Path(output_dir) / "inside.flac"
                inside.write_bytes(b"inside")
                return [
                    SimpleNamespace(output_path=inside),
                    SimpleNamespace(output_path=outside),
                ]

            mock_convert_file.side_effect = convert
            response = self.client.post(
                "/shrink-batch",
                files=[("files", ("recording.wav", b"audio", "audio/wav"))],
                data={"target_bytes": 10000},
            )

        self.assertEqual(response.status_code, 200)
        names, manifest = self._read_archive(response)
        self.assertEqual(names, ["results.json"])
        entry = manifest["results"][0]
        self.assertEqual(entry["status"], "error")
        self.assertEqual(entry["error"], "Processing failed or no output generated")
        self.assertIsNone(entry["output_name"])
        self.assertEqual(entry["output_names"], [])
        self.assertIsNone(entry["output_bytes"])

    @patch("saas_web.media_shrinker.convert_file")
    def test_missing_later_segment_does_not_publish_partial_success(
        self, mock_convert_file
    ) -> None:
        """A missing later segment must not disappear before atomic admission."""

        def convert(source, root, output_dir, target_bytes):
            del source, root, target_bytes
            inside = Path(output_dir) / "inside.flac"
            missing = Path(output_dir) / "missing.flac"
            inside.write_bytes(b"inside")
            return [
                SimpleNamespace(output_path=inside),
                SimpleNamespace(output_path=missing),
            ]

        mock_convert_file.side_effect = convert
        response = self.client.post(
            "/shrink-batch",
            files=[("files", ("recording.wav", b"audio", "audio/wav"))],
            data={"target_bytes": 10000},
        )

        self.assertEqual(response.status_code, 200)
        names, manifest = self._read_archive(response)
        self.assertEqual(names, ["results.json"])
        entry = manifest["results"][0]
        self.assertEqual(entry["status"], "error")
        self.assertEqual(entry["error"], "Processing failed or no output generated")
        self.assertIsNone(entry["output_name"])
        self.assertEqual(entry["output_names"], [])
        self.assertIsNone(entry["output_bytes"])

    @patch("saas_web.media_shrinker.convert_file")
    def test_missing_output_path_does_not_publish_partial_success(
        self, mock_convert_file
    ) -> None:
        """A result without an output path keeps the whole upload entry failed."""

        def convert(source, root, output_dir, target_bytes):
            del source, root, target_bytes
            inside = Path(output_dir) / "inside.flac"
            inside.write_bytes(b"inside")
            return [
                SimpleNamespace(output_path=inside),
                SimpleNamespace(output_path=None),
            ]

        mock_convert_file.side_effect = convert
        response = self.client.post(
            "/shrink-batch",
            files=[("files", ("recording.wav", b"audio", "audio/wav"))],
            data={"target_bytes": 10000},
        )

        self.assertEqual(response.status_code, 200)
        names, manifest = self._read_archive(response)
        self.assertEqual(names, ["results.json"])
        entry = manifest["results"][0]
        self.assertEqual(entry["status"], "error")
        self.assertEqual(entry["error"], "Processing failed or no output generated")
        self.assertIsNone(entry["output_name"])
        self.assertEqual(entry["output_names"], [])
        self.assertIsNone(entry["output_bytes"])

    @patch("saas_web.media_shrinker.convert_file")
    def test_successful_multisegment_entry_records_every_archive_name(
        self, mock_convert_file
    ) -> None:
        """A complete multi-segment result keeps an ordered manifest name list."""

        def convert(source, root, output_dir, target_bytes):
            del source, root, target_bytes
            first = Path(output_dir) / "first.flac"
            second = Path(output_dir) / "second.flac"
            first.write_bytes(b"one")
            second.write_bytes(b"two-two")
            return [
                SimpleNamespace(output_path=first),
                SimpleNamespace(output_path=second),
            ]

        mock_convert_file.side_effect = convert
        response = self.client.post(
            "/shrink-batch",
            files=[("files", ("recording.wav", b"audio", "audio/wav"))],
            data={"target_bytes": 10000},
        )

        self.assertEqual(response.status_code, 200)
        names, manifest = self._read_archive(response)
        expected_outputs = ["01_first.part0001.flac", "01_second.part0002.flac"]
        self.assertEqual(names, sorted([*expected_outputs, "results.json"]))
        entry = manifest["results"][0]
        self.assertEqual(entry["status"], "ok")
        self.assertIsNone(entry["error"])
        self.assertEqual(entry["output_names"], expected_outputs)
        self.assertEqual(entry["output_name"], expected_outputs[-1])
        self.assertEqual(entry["output_bytes"], 10)


if __name__ == "__main__":
    unittest.main()
