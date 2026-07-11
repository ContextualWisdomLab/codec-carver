import asyncio
import io
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from types import SimpleNamespace
try:
    from fastapi import BackgroundTasks
    from fastapi.testclient import TestClient
    from fastapi.responses import Response

    import saas_web
    from saas_web import app

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from media_shrinker import ConversionResult
from job_store import JobStore

if _HAS_FASTAPI:
    client = TestClient(app)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi not installed (optional integration dependency)")
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
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "strict-origin-when-cross-origin",
        )
        self.assertEqual(
            response.headers["Permissions-Policy"],
            "geolocation=(), microphone=(), camera=()",
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
        self.assertIn('onclick="setTargetBytes(26214400)" aria-pressed="false" data-bytes="26214400"', html)
        self.assertIn('onclick="setTargetBytes(104857600)" aria-pressed="false" data-bytes="104857600"', html)
        self.assertIn('onclick="setTargetBytes(524288000)" aria-pressed="false" data-bytes="524288000"', html)
        self.assertIn('onclick="setTargetBytes(1073741824)" aria-pressed="false" data-bytes="1073741824"', html)
        self.assertIn('function setTargetBytes(bytes)', html)

if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(_HAS_FASTAPI, "fastapi not installed (optional integration dependency)")
class JobModelTests(unittest.TestCase):
    """Async job API: submit -> status -> result, plus all error paths."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_store = saas_web.JOB_STORE
        self.addCleanup(setattr, saas_web, "JOB_STORE", self._old_store)
        saas_web.JOB_STORE = JobStore(str(Path(self._tmp.name) / "jobs.db"))

    def tearDown(self) -> None:
        for job in saas_web.JOB_STORE.list_jobs():
            temp = job.get("temp_dir")
            if temp:
                saas_web.cleanup_temp_dir(Path(temp))
            saas_web.JOB_STORE.delete(job["id"])

    def _create_job(
        self,
        job_id: str,
        status: str,
        temp_dir: str,
        output_path: str | None = None,
        output_name: str | None = None,
        error: str | None = None,
    ) -> None:
        """Insert a job-store row for direct endpoint edge-case tests."""

        saas_web.JOB_STORE.create(job_id, temp_dir=temp_dir, now=saas_web._now())
        if status != "queued":
            saas_web.JOB_STORE.set_status(
                job_id,
                status,
                now=saas_web._now(),
                output_path=output_path,
                output_name=output_name,
                error=error,
            )

    @patch("saas_web.media_shrinker.convert_file")
    def test_job_lifecycle_submit_status_result(self, mock_convert_file):
        def fake_convert(**kwargs):
            # Write the output inside the job's real workspace (output_dir), as
            # the engine does, so the served path passes the confinement check.
            output = kwargs["output_dir"] / "out.flac"
            output.write_bytes(b"audio-bytes")
            mock_result = MagicMock(spec=ConversionResult)
            mock_result.output_path = output
            return [mock_result]

        mock_convert_file.side_effect = fake_convert

        submit = client.post(
            "/jobs",
            files={"file": ("in.wav", io.BytesIO(b"wav data"), "audio/wav")},
            data={"target_bytes": 10000},
        )
        self.assertEqual(submit.status_code, 200)
        job_id = submit.json()["job_id"]
        self.assertEqual(submit.json()["status"], "queued")

        status = client.get(f"/jobs/{job_id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "done")

        result = client.get(f"/jobs/{job_id}/result")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content, b"audio-bytes")

    def test_result_outside_workspace_rejected(self):
        # A "done" job whose output escaped its workspace must not be served.
        import tempfile

        workspace = Path(tempfile.mkdtemp(prefix="codec_carver_"))
        outside_dir = Path(tempfile.mkdtemp())
        escaped = outside_dir / "escaped.flac"
        escaped.write_bytes(b"secret")
        try:
            self._create_job(
                "escape",
                "done",
                str(workspace),
                output_path=str(escaped),
                output_name="escaped.flac",
            )
            response = client.get("/jobs/escape/result")
            self.assertEqual(response.status_code, 410)
        finally:
            saas_web.cleanup_temp_dir(workspace)
            saas_web.cleanup_temp_dir(outside_dir)

    def test_submit_rejects_nonpositive_target(self):
        response = client.post(
            "/jobs",
            files={"file": ("in.wav", io.BytesIO(b"wav data"), "audio/wav")},
            data={"target_bytes": 0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("greater than 0", response.json()["error"])

    def test_submit_rejects_missing_filename(self):
        response = saas_web.submit_job(
            BackgroundTasks(),
            file=SimpleNamespace(filename="", file=io.BytesIO(b"wav data")),
            target_bytes=10000,
        )
        self.assertEqual(response.status_code, 400)

    @patch("saas_web._persist_upload", side_effect=OSError("disk full"))
    def test_submit_handles_persist_failure(self, _mock_persist):
        response = saas_web.submit_job(
            BackgroundTasks(),
            file=SimpleNamespace(filename="in.wav", file=io.BytesIO(b"wav data")),
            target_bytes=10000,
        )
        self.assertEqual(response.status_code, 500)

    @patch("saas_web.media_shrinker.convert_file", side_effect=RuntimeError("boom"))
    def test_run_job_records_failure_on_exception(self, _mock_convert):
        submit = client.post(
            "/jobs",
            files={"file": ("in.wav", io.BytesIO(b"wav data"), "audio/wav")},
            data={"target_bytes": 10000},
        )
        job_id = submit.json()["job_id"]
        status = client.get(f"/jobs/{job_id}")
        self.assertEqual(status.json()["status"], "failed")
        self.assertEqual(status.json()["error"], "Processing failed")

    @patch("saas_web.media_shrinker.convert_file", return_value=[])
    def test_run_job_records_failure_on_empty_output(self, _mock_convert):
        submit = client.post(
            "/jobs",
            files={"file": ("in.wav", io.BytesIO(b"wav data"), "audio/wav")},
            data={"target_bytes": 10000},
        )
        job_id = submit.json()["job_id"]
        status = client.get(f"/jobs/{job_id}")
        self.assertEqual(status.json()["status"], "failed")
        self.assertIn("no output", status.json()["error"])

    def test_status_unknown_job_returns_404(self):
        response = client.get("/jobs/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_result_unknown_job_returns_404(self):
        response = client.get("/jobs/does-not-exist/result")
        self.assertEqual(response.status_code, 404)

    def test_result_not_ready_returns_409(self):
        self._create_job("pending", "processing", "")
        response = client.get("/jobs/pending/result")
        self.assertEqual(response.status_code, 409)
        self.assertIn("processing", response.json()["error"])

    def test_result_missing_file_returns_410(self):
        self._create_job(
            "gone",
            "done",
            "",
            output_path="/nonexistent/output.flac",
            output_name="output.flac",
        )
        response = client.get("/jobs/gone/result")
        self.assertEqual(response.status_code, 410)

    def test_cleanup_job_removes_workspace(self):
        import tempfile

        temp_dir = Path(tempfile.mkdtemp(prefix="codec_carver_"))
        self._create_job("c", "done", str(temp_dir))
        saas_web._cleanup_job("c")
        self.assertFalse(temp_dir.exists())
        self.assertIsNone(saas_web.JOB_STORE.get("c"))


@unittest.skipUnless(_HAS_FASTAPI, "fastapi not installed (optional integration dependency)")
class UploadValidationTests(unittest.TestCase):
    """Input hardening surfaced by the SAST review: target bound + content type."""

    def test_shrink_rejects_oversized_target_bytes(self):
        response = client.post(
            "/shrink",
            files={"file": ("in.wav", io.BytesIO(b"wav data"), "audio/wav")},
            data={"target_bytes": saas_web.MAX_TARGET_BYTES + 1},
        )
        self.assertEqual(response.json(), {"error": "Invalid target_bytes value. Exceeds the maximum allowed size."})

    def test_shrink_rejects_non_media_content_type(self):
        response = client.post(
            "/shrink",
            files={"file": ("shell.php", io.BytesIO(b"<?php ?>"), "application/x-php")},
            data={"target_bytes": 10000},
        )
        self.assertEqual(response.json(), {"error": "Unsupported content type; upload an audio or video file."})

    def test_submit_rejects_non_media_content_type(self):
        response = client.post(
            "/jobs",
            files={"file": ("shell.php", io.BytesIO(b"<?php ?>"), "application/x-php")},
            data={"target_bytes": 10000},
        )
        self.assertEqual(response.status_code, 400)

    def test_video_content_type_accepted_by_validator(self):
        self.assertIsNone(
            saas_web._validate_request(
                SimpleNamespace(filename="clip.mp4", content_type="video/mp4"),
                10000,
            )
        )
