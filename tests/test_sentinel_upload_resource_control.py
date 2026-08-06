"""Regression tests for upload validation before temporary-resource allocation.

These tests exercise the security-sensitive branches added by the Sentinel
resource-control fix. Invalid uploads must be rejected before conversion work,
all-invalid batches must still return a useful manifest, temporary-directory
allocation failures must be handled without leaking implementation details, and
fallback upload names must be sanitized before persistence.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

import saas_web


class TestSentinelUploadResourceControl(unittest.TestCase):
    """Verify fail-fast validation and sanitized persistence at upload boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create one in-process HTTP client for endpoint-level regression tests."""

        cls.client = TestClient(saas_web.app)

    @staticmethod
    def _invalid_upload(filename: str = "payload.txt") -> SimpleNamespace:
        """Build a file-like upload that fails the media content-type contract."""

        return SimpleNamespace(
            filename=filename,
            content_type="text/plain",
            file=io.BytesIO(b"not media"),
        )

    @patch("saas_web.media_shrinker.convert_file")
    def test_all_invalid_batch_returns_manifest_without_conversion(
        self, mock_convert_file: MagicMock
    ) -> None:
        """Return validation results without invoking conversion for invalid files."""

        response = self.client.post(
            "/shrink-batch",
            files=[
                ("files", ("first.txt", b"first", "text/plain")),
                ("files", ("second.json", b"{}", "application/json")),
            ],
            data={"target_bytes": 10_000},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.namelist(), ["results.json"])
            manifest = json.loads(archive.read("results.json"))

        self.assertEqual([entry["filename"] for entry in manifest], ["first.txt", "second.json"])
        self.assertTrue(all(entry["status"] == "error" for entry in manifest))
        self.assertTrue(
            all(
                entry["error"]
                == "Unsupported content type; upload an audio or video file."
                for entry in manifest
            )
        )
        mock_convert_file.assert_not_called()

    @patch("saas_web.tempfile.mkdtemp", side_effect=OSError("disk full"))
    def test_all_invalid_batch_handles_manifest_workspace_failure(
        self, _mock_mkdtemp: MagicMock
    ) -> None:
        """Return a sanitized server error when the manifest workspace cannot open."""

        response = saas_web.shrink_media_batch(
            BackgroundTasks(),
            files=[self._invalid_upload()],
            target_bytes=10_000,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            json.loads(response.body),
            {"error": "Upload processing failed"},
        )

    def test_all_invalid_batch_cleans_workspace_after_manifest_write_failure(self) -> None:
        """Delete the allocated batch workspace when manifest archive writing fails."""

        with tempfile.TemporaryDirectory() as parent_directory:
            workspace = Path(parent_directory) / "codec_carver_batch_failure"
            workspace.mkdir()
            with (
                patch("saas_web.tempfile.mkdtemp", return_value=str(workspace)),
                patch.object(
                    zipfile.ZipFile,
                    "writestr",
                    side_effect=OSError("manifest write failed"),
                ),
            ):
                response = saas_web.shrink_media_batch(
                    BackgroundTasks(),
                    files=[self._invalid_upload()],
                    target_bytes=10_000,
                )

            self.assertEqual(response.status_code, 500)
            self.assertEqual(
                json.loads(response.body),
                {"error": "Upload processing failed"},
            )
            self.assertFalse(workspace.exists())

    @patch("saas_web.uuid.uuid4")
    @patch("saas_web._get_job_store")
    @patch("saas_web._persist_upload")
    def test_submit_job_sanitizes_filename_before_persistence(
        self,
        mock_persist_upload: MagicMock,
        mock_get_job_store: MagicMock,
        mock_uuid4: MagicMock,
    ) -> None:
        """Pass a safe fallback filename into persistence before allocating a job."""

        temp_dir = Path("/tmp/codec-carver-test")
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        source_path = input_dir / "upload.tmp"
        mock_persist_upload.return_value = (
            temp_dir,
            input_dir,
            output_dir,
            source_path,
        )
        mock_uuid4.return_value.hex = "sentinel-job"
        store = mock_get_job_store.return_value
        upload = SimpleNamespace(filename=".", file=io.BytesIO(b"media"))
        background_tasks = BackgroundTasks()

        response = saas_web.submit_job(
            background_tasks,
            file=upload,
            target_bytes=10_000,
        )

        self.assertEqual(response, {"job_id": "sentinel-job", "status": "queued"})
        mock_persist_upload.assert_called_once_with(upload, "upload.tmp")
        store.create.assert_called_once()
        self.assertEqual(len(background_tasks.tasks), 1)


if __name__ == "__main__":
    unittest.main()
