import asyncio
import io
import json
import unittest
import zipfile
from unittest.mock import patch, MagicMock
from pathlib import Path
from types import SimpleNamespace
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from fastapi.responses import Response

import saas_web
from saas_web import app
from media_shrinker import ConversionResult

client = TestClient(app)

class TestSaasWeb(unittest.TestCase):

    def test_get_ui(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Codec Carver SaaS", response.content)

    def test_get_ui_includes_accessible_file_input_helpers(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn('accept="audio/*,video/*"', html)
        self.assertIn('aria-describedby="file_help file_size_preview"', html)
        self.assertIn('id="file_help"', html)
        self.assertIn('class="required-star" aria-hidden="true"', html)

    def test_get_ui_includes_binary_file_size_validation(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("const MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;", html)
        self.assertIn("['B', 'KiB', 'MiB', 'GiB']", html)
        self.assertIn("File exceeds 5 GiB limit.", html)
        self.assertIn("preview.style.color = '#0f6674';", html)
        self.assertIn('onchange="updateFileSizePreview(this)"', html)

    def test_security_headers_present_without_plain_http_hsts(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-XSS-Protection"], "1; mode=block")
        self.assertEqual(
            response.headers["Content-Security-Policy"],
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
        )
        self.assertNotIn("Strict-Transport-Security", response.headers)

    def test_hsts_header_present_for_forwarded_https(self):
        response = client.get("/", headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Strict-Transport-Security"],
            "max-age=31536000; includeSubDomains",
        )

    def test_request_size_limit_rejects_oversized_declared_body(self):
        response = client.post(
            "/shrink",
            headers={"Content-Length": str(saas_web.MAX_REQUEST_BYTES + 1)},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"error": "Payload Too Large"})

    def test_request_size_limit_rejects_invalid_content_length(self):
        response = client.post(
            "/shrink",
            headers={"Content-Length": "not-a-number"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Invalid Content-Length"})

    def test_request_size_limit_rejects_negative_content_length(self):
        response = client.post(
            "/shrink",
            headers={"Content-Length": "-1"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Invalid Content-Length"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_media_endpoint(self, mock_convert_file):
        # Create a dummy output file for the FileResponse
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_output = Path(temp_dir) / "output.flac"
            temp_output.write_bytes(b"dummy audio data")

            # Setup mock return value
            mock_result = MagicMock(spec=ConversionResult)
            mock_result.output_path = temp_output
            mock_convert_file.return_value = [mock_result]

            # Create a dummy upload file
            dummy_file_path = Path(temp_dir) / "input.wav"
            dummy_file_path.write_bytes(b"dummy wav data")

            with open(dummy_file_path, "rb") as f:
                response = client.post(
                    "/shrink",
                    files={"file": ("input.wav", f, "audio/wav")},
                    data={"target_bytes": 10000}
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"dummy audio data")

            # Verify the mock was called
            mock_convert_file.assert_called_once()

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_media_failure(self, mock_convert_file):
        # Setup mock to return empty or error
        mock_convert_file.return_value = []

        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            dummy_file_path = Path(temp_dir) / "input.wav"
            dummy_file_path.write_bytes(b"dummy wav data")

            with open(dummy_file_path, "rb") as f:
                response = client.post(
                    "/shrink",
                    files={"file": ("input.wav", f, "audio/wav")},
                    data={"target_bytes": 10000}
                )

            self.assertEqual(response.status_code, 200) # Returns 200 with JSON error dict currently
            self.assertIn(b"error", response.content)
            self.assertNotIn("details", response.json())

    def test_shrink_media_rejects_nonpositive_target_bytes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            dummy_file_path = Path(temp_dir) / "input.wav"
            dummy_file_path.write_bytes(b"dummy wav data")

            with open(dummy_file_path, "rb") as f:
                response = client.post(
                    "/shrink",
                    files={"file": ("input.wav", f, "audio/wav")},
                    data={"target_bytes": 0},
                )

        self.assertEqual(
            response.json(),
            {"error": "Invalid target_bytes value. Must be greater than 0."},
        )

    def test_shrink_media_rejects_missing_filename(self):
        response = saas_web.shrink_media(
            BackgroundTasks(),
            file=SimpleNamespace(filename="", file=io.BytesIO(b"dummy wav data")),
            target_bytes=10000,
        )

        self.assertEqual(response, {"error": "No file uploaded or filename missing"})

    @patch("saas_web.tempfile.mkdtemp", side_effect=OSError("disk full"))
    def test_shrink_media_handles_temp_dir_failure(self, _mock_mkdtemp):
        response = saas_web.shrink_media(
            BackgroundTasks(),
            file=SimpleNamespace(
                filename="input.wav", file=io.BytesIO(b"dummy wav data")
            ),
            target_bytes=10000,
        )

        self.assertEqual(response, {"error": "Upload processing failed"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_media_uses_safe_fallback_filename(self, mock_convert_file):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output.flac"
            output.write_bytes(b"audio")
            mock_result = MagicMock(spec=ConversionResult)
            mock_result.output_path = output
            mock_convert_file.return_value = [mock_result]

            response = saas_web.shrink_media(
                BackgroundTasks(),
                file=SimpleNamespace(filename=".", file=io.BytesIO(b"dummy wav data")),
                target_bytes=10000,
            )

        self.assertEqual(Path(response.path), output)
        self.assertEqual(
            mock_convert_file.call_args.kwargs["source"].name, "upload.tmp"
        )

    def test_shrink_media_rejects_uploaded_body_over_limit(self):
        previous_limit = saas_web.MAX_UPLOAD_BYTES
        saas_web.MAX_UPLOAD_BYTES = 3
        try:
            response = saas_web.shrink_media(
                BackgroundTasks(),
                file=SimpleNamespace(filename="input.wav", file=io.BytesIO(b"1234")),
                target_bytes=10000,
            )
        finally:
            saas_web.MAX_UPLOAD_BYTES = previous_limit

        self.assertEqual(response, {"error": "Upload processing failed"})

    @patch("saas_web.Path.mkdir", side_effect=OSError("mkdir failed"))
    def test_shrink_media_handles_workspace_prepare_failure(self, _mock_mkdir):
        response = saas_web.shrink_media(
            BackgroundTasks(),
            file=SimpleNamespace(
                filename="input.wav", file=io.BytesIO(b"dummy wav data")
            ),
            target_bytes=10000,
        )

        self.assertEqual(response, {"error": "Upload processing failed"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_media_exception_does_not_expose_internal_path(self, mock_convert_file):
        mock_convert_file.side_effect = RuntimeError("/tmp/codec_carver_secret/input.wav")

        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            dummy_file_path = Path(temp_dir) / "input.wav"
            dummy_file_path.write_bytes(b"dummy wav data")

            with open(dummy_file_path, "rb") as f:
                response = client.post(
                    "/shrink",
                    files={"file": ("input.wav", f, "audio/wav")},
                    data={"target_bytes": 10000}
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload, {"error": "Upload processing failed"})
            self.assertNotIn("/tmp/codec_carver_secret", response.text)

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_media_failed_result_does_not_expose_internal_path(self, mock_convert_file):
        mock_result = MagicMock(spec=ConversionResult)
        mock_result.output_path = Path("/tmp/codec_carver_secret/output.flac")
        mock_convert_file.return_value = [mock_result]

        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            dummy_file_path = Path(temp_dir) / "input.wav"
            dummy_file_path.write_bytes(b"dummy wav data")

            with open(dummy_file_path, "rb") as f:
                response = client.post(
                    "/shrink",
                    files={"file": ("input.wav", f, "audio/wav")},
                    data={"target_bytes": 10000}
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload, {"error": "Processing failed or no output generated"})
            self.assertNotIn("/tmp/codec_carver_secret", response.text)


    def test_get_ui_includes_target_bytes_validation_feedback(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("preview.innerText = 'Must be greater than 0.';", html)
        self.assertIn("preview.style.color = '#dc3545';", html)

    def test_request_size_limit_rejects_streamed_body_over_limit(self):
        async def receive():
            return {"type": "http.request", "body": b"1234"}

        async def call_next(request):
            await request._receive()
            return Response()

        request = SimpleNamespace(headers={}, _receive=receive)
        previous_limit = saas_web.MAX_REQUEST_BYTES
        saas_web.MAX_REQUEST_BYTES = 3
        try:
            response = asyncio.run(saas_web.limit_request_size(request, call_next))
        finally:
            saas_web.MAX_REQUEST_BYTES = previous_limit

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.body, b'{"error":"Payload Too Large"}')

    def test_get_ui_includes_preset_buttons(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn('class="preset-container"', html)
        self.assertIn('onclick="setTargetBytes(26214400)"', html)
        self.assertIn('onclick="setTargetBytes(104857600)"', html)
        self.assertIn('onclick="setTargetBytes(524288000)"', html)
        self.assertIn('onclick="setTargetBytes(1073741824)"', html)
        self.assertIn('function setTargetBytes(bytes)', html)

class TestShrinkBatch(unittest.TestCase):
    """Tests for the POST /shrink-batch multi-file endpoint."""

    @staticmethod
    def _fake_convert(source, root, output_dir, target_bytes):
        """Fake convert_file that writes a shrunk copy into output_dir."""
        output_path = Path(output_dir) / (Path(source).stem + ".flac")
        output_path.write_bytes(b"shrunk:" + Path(source).read_bytes())
        result = MagicMock(spec=ConversionResult)
        result.output_path = output_path
        return [result]

    @staticmethod
    def _read_zip(response):
        """Return (namelist, manifest dict, zipfile) for a zip response."""
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        manifest = json.loads(archive.read("results.json"))
        return archive.namelist(), manifest, archive

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_batch_two_files_returns_zip_with_outputs_and_manifest(self, mock_convert_file):
        mock_convert_file.side_effect = self._fake_convert

        response = client.post(
            "/shrink-batch",
            files=[
                ("files", ("a.wav", b"audio-a", "audio/wav")),
                ("files", ("b.mp4", b"video-b", "video/mp4")),
            ],
            data={"target_bytes": 10000},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        names, manifest, archive = self._read_zip(response)
        self.assertIn("01_a.flac", names)
        self.assertIn("02_b.flac", names)
        self.assertIn("results.json", names)
        self.assertEqual(archive.read("01_a.flac"), b"shrunk:audio-a")
        self.assertEqual(archive.read("02_b.flac"), b"shrunk:video-b")
        self.assertEqual(manifest["target_bytes"], 10000)
        self.assertEqual(len(manifest["results"]), 2)
        self.assertEqual(manifest["results"][0]["status"], "ok")
        self.assertEqual(manifest["results"][0]["filename"], "a.wav")
        self.assertEqual(manifest["results"][0]["output_name"], "01_a.flac")
        self.assertEqual(manifest["results"][0]["output_bytes"], len(b"shrunk:audio-a"))
        self.assertEqual(manifest["results"][1]["status"], "ok")
        self.assertEqual(mock_convert_file.call_count, 2)

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_batch_one_failure_does_not_abort_batch(self, mock_convert_file):
        def convert(source, root, output_dir, target_bytes):
            if Path(source).name == "bad.wav":
                raise RuntimeError("/tmp/codec_carver_secret/bad.wav")
            return self._fake_convert(source, root, output_dir, target_bytes)

        mock_convert_file.side_effect = convert

        response = client.post(
            "/shrink-batch",
            files=[
                ("files", ("bad.wav", b"broken", "audio/wav")),
                ("files", ("good.wav", b"fine", "audio/wav")),
            ],
            data={"target_bytes": 10000},
        )

        self.assertEqual(response.status_code, 200)
        names, manifest, archive = self._read_zip(response)
        self.assertNotIn("01_bad.flac", names)
        self.assertIn("02_good.flac", names)
        self.assertEqual(manifest["results"][0]["status"], "error")
        self.assertEqual(manifest["results"][0]["error"], "Upload processing failed")
        self.assertNotIn("codec_carver_secret", archive.read("results.json").decode())
        self.assertEqual(manifest["results"][1]["status"], "ok")

    def test_shrink_batch_rejects_zero_files(self):
        response = client.post("/shrink-batch", data={"target_bytes": 10000})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "No files uploaded"})

    def test_shrink_batch_rejects_too_many_files(self):
        uploads = [
            ("files", (f"f{i}.wav", b"x", "audio/wav"))
            for i in range(saas_web.MAX_BATCH_FILES + 1)
        ]
        response = client.post("/shrink-batch", files=uploads, data={"target_bytes": 10000})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": f"Too many files. Maximum is {saas_web.MAX_BATCH_FILES} files per batch."},
        )

    def test_shrink_batch_rejects_nonpositive_target_bytes(self):
        response = client.post(
            "/shrink-batch",
            files=[("files", ("a.wav", b"audio", "audio/wav"))],
            data={"target_bytes": 0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": "Invalid target_bytes value. Must be greater than 0."},
        )

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_batch_rejects_disallowed_content_type_per_file(self, mock_convert_file):
        mock_convert_file.side_effect = self._fake_convert

        response = client.post(
            "/shrink-batch",
            files=[
                ("files", ("evil.sh", b"#!/bin/sh", "application/x-sh")),
                ("files", ("good.wav", b"fine", "audio/wav")),
            ],
            data={"target_bytes": 10000},
        )

        self.assertEqual(response.status_code, 200)
        names, manifest, _archive = self._read_zip(response)
        self.assertEqual(names, ["02_good.flac", "results.json"])
        self.assertEqual(manifest["results"][0]["status"], "error")
        self.assertIn("Unsupported content type", manifest["results"][0]["error"])
        self.assertEqual(manifest["results"][1]["status"], "ok")
        mock_convert_file.assert_called_once()

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_batch_records_no_output_as_error(self, mock_convert_file):
        mock_convert_file.return_value = []

        response = client.post(
            "/shrink-batch",
            files=[("files", ("a.wav", b"audio", "audio/wav"))],
            data={"target_bytes": 10000},
        )

        self.assertEqual(response.status_code, 200)
        names, manifest, _archive = self._read_zip(response)
        self.assertEqual(names, ["results.json"])
        self.assertEqual(manifest["results"][0]["status"], "error")
        self.assertEqual(
            manifest["results"][0]["error"],
            "Processing failed or no output generated",
        )

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_batch_never_serves_output_outside_workspace(self, mock_convert_file):
        import tempfile
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_file = Path(outside_dir) / "secret.flac"
            outside_file.write_bytes(b"secret contents")
            mock_result = MagicMock(spec=ConversionResult)
            mock_result.output_path = outside_file
            mock_convert_file.return_value = [mock_result]

            response = client.post(
                "/shrink-batch",
                files=[("files", ("a.wav", b"audio", "audio/wav"))],
                data={"target_bytes": 10000},
            )

        self.assertEqual(response.status_code, 200)
        names, manifest, _archive = self._read_zip(response)
        self.assertEqual(names, ["results.json"])
        self.assertEqual(manifest["results"][0]["status"], "error")
        self.assertEqual(
            manifest["results"][0]["error"],
            "Processing failed or no output generated",
        )
        self.assertNotIn(b"secret contents", response.content)

    def test_shrink_batch_records_oversized_file_as_error(self):
        previous_limit = saas_web.MAX_UPLOAD_BYTES
        saas_web.MAX_UPLOAD_BYTES = 3
        try:
            response = client.post(
                "/shrink-batch",
                files=[("files", ("big.wav", b"12345", "audio/wav"))],
                data={"target_bytes": 10000},
            )
        finally:
            saas_web.MAX_UPLOAD_BYTES = previous_limit

        self.assertEqual(response.status_code, 200)
        names, manifest, _archive = self._read_zip(response)
        self.assertEqual(names, ["results.json"])
        self.assertEqual(manifest["results"][0]["status"], "error")
        self.assertEqual(manifest["results"][0]["error"], "Upload processing failed")

    @patch("saas_web.tempfile.mkdtemp", side_effect=OSError("disk full"))
    def test_shrink_batch_handles_workspace_creation_failure(self, _mock_mkdtemp):
        response = client.post(
            "/shrink-batch",
            files=[("files", ("a.wav", b"audio", "audio/wav"))],
            data={"target_bytes": 10000},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "Upload processing failed"})

    @patch("saas_web.zipfile.ZipFile", side_effect=OSError("cannot write zip"))
    def test_shrink_batch_handles_archive_failure(self, _mock_zipfile):
        response = client.post(
            "/shrink-batch",
            files=[("files", ("a.wav", b"audio", "audio/wav"))],
            data={"target_bytes": 10000},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "Upload processing failed"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_batch_uses_safe_fallback_filename(self, mock_convert_file):
        mock_convert_file.return_value = []

        response = saas_web.shrink_media_batch(
            BackgroundTasks(),
            files=[
                SimpleNamespace(
                    filename="..",
                    content_type="audio/wav",
                    file=io.BytesIO(b"dummy"),
                )
            ],
            target_bytes=10000,
        )

        archive = zipfile.ZipFile(response.path)
        manifest = json.loads(archive.read("results.json"))
        self.assertEqual(manifest["results"][0]["filename"], "upload.tmp")
        self.assertEqual(
            mock_convert_file.call_args.kwargs["source"].name, "upload.tmp"
        )
        saas_web.cleanup_temp_dir(Path(response.path).parent)

    def test_get_ui_includes_batch_upload_form(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('action="/shrink-batch"', html)
        self.assertIn('id="batch_files"', html)
        self.assertIn('multiple', html)
        self.assertIn('accept="audio/*,video/*"', html)


if __name__ == '__main__':
    unittest.main()
