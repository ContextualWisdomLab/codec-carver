import asyncio
import io
import json
import os
import tempfile
import unittest
import zipfile
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


@unittest.skipUnless(
    _HAS_FASTAPI, "fastapi not installed (optional integration dependency)"
)
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

    def test_get_ui_renders_server_target_limit_and_numeric_validation(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertNotIn("__MAX_TARGET_BYTES__", html)
        self.assertEqual(
            html.count(f'max="{saas_web.MAX_TARGET_BYTES}"'),
            2,
        )
        self.assertIn(
            f"const MAX_TARGET_BYTES = {saas_web.MAX_TARGET_BYTES};",
            html,
        )
        self.assertEqual(html.count("const val = this.valueAsNumber;"), 2)
        self.assertEqual(html.count("Number.isNaN(val)"), 2)
        self.assertEqual(html.count("val > MAX_TARGET_BYTES"), 2)

        max_message = (
            "const maxTargetMessage = 'Enter a target size of ' + limitText + "
            "' or less.';"
        )
        self.assertEqual(html.count(max_message), 2)
        self.assertEqual(html.count("preview.innerText = maxTargetMessage;"), 2)
        self.assertEqual(html.count("this.setCustomValidity(maxTargetMessage);"), 2)
        self.assertEqual(
            html.count("Enter a target size greater than 0 bytes."),
            4,
        )
        self.assertNotIn("Cannot exceed ' + limitText", html)
        self.assertNotIn("Must be greater than 0.", html)

    def test_get_ui_includes_binary_file_size_validation(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("const MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;", html)
        self.assertIn("['B', 'KiB', 'MiB', 'GiB']", html)
        self.assertIn("const limitText = formatBinaryBytes(MAX_UPLOAD_BYTES);", html)
        self.assertIn("File exceeds ' + limitText + ' limit.", html)
        self.assertIn("Total file size exceeds ' + limitText + ' limit.", html)
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
                    data={"target_bytes": 10000},
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
                    data={"target_bytes": 10000},
                )

            self.assertEqual(
                response.status_code, 200
            )  # Returns 200 with JSON error dict currently
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

        self.assertEqual(response, {"error": "Uploaded file exceeds the size limit"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_media_rejects_output_outside_temp_dir(self, mock_convert_file):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            outside = temp_path.parent / f"outside-{temp_path.name}.flac"
            outside.write_bytes(b"outside")
            try:
                mock_result = MagicMock(spec=ConversionResult)
                mock_result.output_path = outside
                mock_convert_file.return_value = [mock_result]

                with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
                    response = saas_web.shrink_media(
                        BackgroundTasks(),
                        file=SimpleNamespace(
                            filename="input.wav", file=io.BytesIO(b"dummy wav data")
                        ),
                        target_bytes=10000,
                    )

                self.assertEqual(response, {"error": "Conversion output invalid"})
                self.assertNotIn("details", response)
            finally:
                outside.unlink(missing_ok=True)

    @patch("saas_web.media_shrinker.convert_file")
    def test_shrink_media_allows_output_inside_temp_dir(self, mock_convert_file):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output.flac"
            output.write_bytes(b"inside")
            mock_result = MagicMock(spec=ConversionResult)
            mock_result.output_path = output
            mock_convert_file.return_value = [mock_result]

            with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
                response = saas_web.shrink_media(
                    BackgroundTasks(),
                    file=SimpleNamespace(
                        filename="input.wav", file=io.BytesIO(b"dummy wav data")
                    ),
                    target_bytes=10000,
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"inside")

    def test_upload_dir_rejects_oversized_upload_without_filename(self):
        previous_limit = saas_web.MAX_UPLOAD_BYTES
        saas_web.MAX_UPLOAD_BYTES = 3
        try:
            response = saas_web.shrink_media(
                BackgroundTasks(),
                file=SimpleNamespace(filename="", file=io.BytesIO(b"1234")),
                target_bytes=10000,
            )
        finally:
            saas_web.MAX_UPLOAD_BYTES = previous_limit

        self.assertEqual(response, {"error": "Uploaded file exceeds the size limit"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_conversion_result_symlink_is_rejected(self, mock_convert_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            outside = temp_path.parent / f"outside-{temp_path.name}.flac"
            outside.write_bytes(b"outside")
            link = temp_path / "output.flac"
            try:
                link.symlink_to(outside)
                mock_result = MagicMock(spec=ConversionResult)
                mock_result.output_path = link
                mock_convert_file.return_value = [mock_result]

                with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
                    response = saas_web.shrink_media(
                        BackgroundTasks(),
                        file=SimpleNamespace(
                            filename="input.wav", file=io.BytesIO(b"dummy wav data")
                        ),
                        target_bytes=10000,
                    )

                self.assertEqual(response, {"error": "Conversion output invalid"})
            finally:
                outside.unlink(missing_ok=True)

    def test_safe_archive_member_name_normalizes_dangerous_components(self):
        self.assertEqual(
            saas_web._safe_archive_member_name(Path("/srv/out/unsafe:name?.flac"), 7),
            "7-unsafe_name_.flac",
        )
        self.assertEqual(
            saas_web._safe_archive_member_name(Path("CON.mp3"), 2), "2-file_CON.mp3"
        )

    def test_safe_archive_member_name_falls_back_when_sanitized_name_is_empty(self):
        self.assertEqual(
            saas_web._safe_archive_member_name(Path("..."), 3), "3-output.bin"
        )

    def test_build_archive_payload_uses_safe_deterministic_member_names(self):
        results = [
            SimpleNamespace(output_path=Path("/srv/out/clip one.flac")),
            SimpleNamespace(output_path=Path("/srv/out/clip one.flac")),
        ]
        output = io.BytesIO()
        with patch("saas_web.zipfile.ZipFile") as zip_file:
            archive = MagicMock()
            zip_file.return_value.__enter__.return_value = archive

            saas_web._build_archive_payload(results, output)

        written_names = [call.args[1] for call in archive.write.call_args_list]
        self.assertEqual(written_names, ["1-clip_one.flac", "2-clip_one.flac"])

    def test_build_archive_payload_cleans_partial_buffer_when_write_fails(self):
        results = [SimpleNamespace(output_path=Path("/srv/out/clip.flac"))]
        output = io.BytesIO(b"stale")

        with patch("saas_web.zipfile.ZipFile") as zip_file:
            archive = MagicMock()
            archive.write.side_effect = OSError("disk full")
            zip_file.return_value.__enter__.return_value = archive

            with self.assertRaises(OSError):
                saas_web._build_archive_payload(results, output)

        self.assertEqual(output.getvalue(), b"")

    def test_sanitize_stem_for_filename_makes_safe_filename(self):
        # Test dangerous characters
        self.assertEqual(saas_web.sanitize_stem_for_filename("My:Song?"), "My_Song_")
        self.assertEqual(saas_web.sanitize_stem_for_filename("a/b\\c"), "a_b_c")
        # Test leading/trailing dots/spaces stripped
        self.assertEqual(saas_web.sanitize_stem_for_filename("  ..myfile..  "), "myfile")
        # Test empty after sanitization
        self.assertEqual(saas_web.sanitize_stem_for_filename("..."), "file")
        # Test Windows reserved names
        self.assertEqual(saas_web.sanitize_stem_for_filename("CON"), "file_CON")
        self.assertEqual(saas_web.sanitize_stem_for_filename("con.txt"), "file_con.txt")
        self.assertEqual(saas_web.sanitize_stem_for_filename("LPT1"), "file_LPT1")
        self.assertEqual(saas_web.sanitize_stem_for_filename("LPT9.txt"), "file_LPT9.txt")
        self.assertEqual(saas_web.sanitize_stem_for_filename("COM1"), "file_COM1")
        self.assertEqual(saas_web.sanitize_stem_for_filename("AUX"), "file_AUX")
        # Test max length
        long_name = "a" * 300
        self.assertEqual(len(saas_web.sanitize_stem_for_filename(long_name)), 240)
        # Test normal name
        self.assertEqual(saas_web.sanitize_stem_for_filename("my_file-123"), "my_file-123")

    def test_sanitize_stem_for_filename_reserved_name_after_truncation(self):
        long_name = ("a" * 238) + "CON"
        sanitized = saas_web.sanitize_stem_for_filename(long_name)
        self.assertLessEqual(len(sanitized), 240)
        self.assertFalse(saas_web._is_windows_reserved_filename(sanitized))

    def test_is_windows_reserved_filename_handles_trailing_space_dot(self):
        self.assertTrue(saas_web._is_windows_reserved_filename("CON .txt"))
        self.assertTrue(saas_web._is_windows_reserved_filename("lpt1..."))
        self.assertFalse(saas_web._is_windows_reserved_filename("container.txt"))

    def test_cleanup_temp_dir_noop_for_missing_path(self):
        saas_web.cleanup_temp_dir(None)

    def test_cleanup_temp_dir_removes_directory(self):
        import tempfile

        temp_dir = tempfile.mkdtemp()
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("test")

        saas_web.cleanup_temp_dir(temp_dir)
        self.assertFalse(Path(temp_dir).exists())

    @patch("saas_web.shutil.rmtree", side_effect=OSError("boom"))
    def test_cleanup_temp_dir_handles_errors(self, _mock_rmtree):
        with patch("builtins.print") as mock_print:
            saas_web.cleanup_temp_dir("/tmp/does-not-matter")
        mock_print.assert_called_once_with("Failed to clean up temporary directory")

    @patch("saas_web.tempfile.mkdtemp", side_effect=OSError("disk full"))
    def test_batch_shrink_handles_temp_dir_failure(self, _mock_mkdtemp):
        response = saas_web.batch_shrink_media(
            BackgroundTasks(),
            files=[
                SimpleNamespace(filename="input.wav", file=io.BytesIO(b"dummy wav data"))
            ],
            target_bytes=10000,
        )
        self.assertEqual(response, {"error": "Upload processing failed"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_batch_shrink_all_unsafe_outputs_are_rejected(self, mock_convert_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            outside = temp_path.parent / f"outside-{temp_path.name}.flac"
            outside.write_bytes(b"outside")
            try:
                mock_result = MagicMock(spec=ConversionResult)
                mock_result.output_path = outside
                mock_convert_file.return_value = [mock_result]

                with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
                    response = saas_web.batch_shrink_media(
                        BackgroundTasks(),
                        files=[
                            SimpleNamespace(
                                filename="input.wav", file=io.BytesIO(b"dummy wav data")
                            )
                        ],
                        target_bytes=10000,
                    )

                self.assertEqual(response, {"error": "No successful conversions"})
            finally:
                outside.unlink(missing_ok=True)

    @patch("saas_web.media_shrinker.convert_file")
    def test_batch_shrink_archive_failure_returns_safe_error(self, mock_convert_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "inside.flac"
            output.write_bytes(b"inside")
            mock_result = MagicMock(spec=ConversionResult)
            mock_result.output_path = output
            mock_convert_file.return_value = [mock_result]

            with patch(
                "saas_web._build_archive_payload",
                side_effect=OSError("archive exploded"),
            ):
                response = saas_web.batch_shrink_media(
                    BackgroundTasks(),
                    files=[
                        SimpleNamespace(
                            filename="input.wav", file=io.BytesIO(b"dummy wav data")
                        )
                    ],
                    target_bytes=10000,
                )

            self.assertEqual(response, {"error": "Archive creation failed"})

    @patch("saas_web.media_shrinker.convert_file")
    def test_batch_shrink_filters_outputs_outside_temp_dir(self, mock_convert_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            inside = temp_path / "inside.flac"
            outside = temp_path.parent / f"outside-{temp_path.name}.flac"
            inside.write_bytes(b"inside")
            outside.write_bytes(b"outside")
            try:
                inside_result = MagicMock(spec=ConversionResult)
                inside_result.output_path = inside
                outside_result = MagicMock(spec=ConversionResult)
                outside_result.output_path = outside
                mock_convert_file.return_value = [inside_result, outside_result]

                with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
                    response = saas_web.batch_shrink_media(
                        BackgroundTasks(),
                        files=[
                            SimpleNamespace(
                                filename="input.wav", file=io.BytesIO(b"dummy wav data")
                            )
                        ],
                        target_bytes=10000,
                    )

                self.assertEqual(response.media_type, "application/zip")
                archive = zipfile.ZipFile(io.BytesIO(response.body), "r")
                self.assertEqual(archive.namelist(), ["1-inside.flac"])
            finally:
                outside.unlink(missing_ok=True)

    @patch("saas_web.media_shrinker.convert_file")
    def test_batch_shrink_no_successful_conversions_cleans_temp_dir(
        self, mock_convert_file
    ):
        mock_convert_file.return_value = []
        temp_dir = tempfile.mkdtemp()
        with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
            response = saas_web.batch_shrink_media(
                BackgroundTasks(),
                files=[
                    SimpleNamespace(filename="input.wav", file=io.BytesIO(b"dummy wav data"))
                ],
                target_bytes=10000,
            )

        self.assertEqual(response, {"error": "No successful conversions"})
        self.assertFalse(Path(temp_dir).exists())

    @patch("saas_web.media_shrinker.convert_file")
    def test_batch_shrink_exception_cleans_temp_dir(self, mock_convert_file):
        mock_convert_file.side_effect = RuntimeError("boom")
        temp_dir = tempfile.mkdtemp()
        with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
            response = saas_web.batch_shrink_media(
                BackgroundTasks(),
                files=[
                    SimpleNamespace(filename="input.wav", file=io.BytesIO(b"dummy wav data"))
                ],
                target_bytes=10000,
            )

        self.assertEqual(response, {"error": "Batch processing failed"})
        self.assertFalse(Path(temp_dir).exists())

    @patch("saas_web.media_shrinker.convert_file")
    def test_batch_shrink_media_endpoint(self, mock_convert_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_one = temp_path / "out-one.flac"
            output_two = temp_path / "out-two.flac"
            output_one.write_bytes(b"one")
            output_two.write_bytes(b"two")

            result_one = MagicMock(spec=ConversionResult)
            result_one.output_path = output_one
            result_two = MagicMock(spec=ConversionResult)
            result_two.output_path = output_two
            mock_convert_file.side_effect = [[result_one], [result_two]]

            with patch("saas_web.tempfile.mkdtemp", return_value=temp_dir):
                response = saas_web.batch_shrink_media(
                    BackgroundTasks(),
                    files=[
                        SimpleNamespace(filename="a.wav", file=io.BytesIO(b"audio-a")),
                        SimpleNamespace(filename="b.wav", file=io.BytesIO(b"audio-b")),
                    ],
                    target_bytes=10000,
                )

            self.assertEqual(response.media_type, "application/zip")
            archive = zipfile.ZipFile(io.BytesIO(response.body), "r")
            self.assertEqual(archive.namelist(), ["1-out-one.flac", "2-out-two.flac"])

            self.assertEqual(mock_convert_file.call_count, 2)
            for call in mock_convert_file.call_args_list:
                self.assertEqual(call.kwargs["target_bytes"], 10000)
