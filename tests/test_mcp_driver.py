"""Test module."""
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from mcp_driver import shrink_media
from media_shrinker import ConversionResult

class TestMCPDriver(unittest.TestCase):
    """Test class."""

    @patch("mcp_driver.media_shrinker.convert_file")
    def test_shrink_media_success(self, mock_convert_file):
        """Test method."""
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            source_file = temp_dir_path / "source.wav"
            source_file.touch()
            output_dir = temp_dir_path / "output"

            mock_result = MagicMock(spec=ConversionResult)
            mock_result.status = "success"
            mock_result.output_path = output_dir / "source.flac"
            mock_result.strategy = "flac"
            mock_result.message = "converted"

            mock_convert_file.return_value = [mock_result]

            result_str = shrink_media(str(source_file), str(output_dir), 1000)

            mock_convert_file.assert_called_once()
            self.assertIn("Status: success", result_str)
            self.assertIn("Output: " + str(output_dir / "source.flac"), result_str)

    def test_shrink_media_source_not_found(self):
        """Test method."""
        result_str = shrink_media("/path/does/not/exist.wav", "/tmp/out")
        self.assertIn("Error: Source file does not exist", result_str)

    @patch("mcp_driver.media_shrinker.convert_file")
    def test_shrink_media_exception(self, mock_convert_file):
        """Test method."""
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            source_file = temp_dir_path / "source.wav"
            source_file.touch()
            output_dir = temp_dir_path / "output"

            mock_convert_file.side_effect = Exception("Test FFmpeg error")

            result_str = shrink_media(str(source_file), str(output_dir))

            self.assertIn("Conversion failed with error: Test FFmpeg error", result_str)

if __name__ == '__main__':
    unittest.main()
