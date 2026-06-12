import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from fastapi.testclient import TestClient

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
        self.assertIn('aria-describedby="file_help"', html)
        self.assertIn('id="file_help"', html)
        self.assertIn('class="required-star" aria-hidden="true"', html)

    @patch("saas_web.media_shrinker.convert_file")
    @patch("saas_web.tempfile.mkdtemp")
    def test_shrink_media_success(self, mock_mkdtemp, mock_convert_file):
        # Setup mock temp dir
        mock_temp_dir = "/tmp/mock_temp"
        mock_mkdtemp.return_value = mock_temp_dir

        # We need to mock the path objects to prevent actual file system operations if possible
        # Or let the endpoint create the temp dir structure in the actual /tmp
        pass # To properly test, it's better to let tempfile work or mock properly.

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

if __name__ == '__main__':
    unittest.main()
