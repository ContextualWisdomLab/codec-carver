"""Tests for the MCP driver interface."""
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from mcp_driver import shrink_media

class McpDriverTests(unittest.TestCase):
    """Test suite for the MCP driver functionality."""
    @patch('mcp_driver.media_shrinker.convert_file')
    def test_shrink_media_success(self, mock_convert_file):
        """Test successful media conversion through MCP driver."""
        mock_result = MagicMock()
        mock_result.output_path = Path("/tmp/output.flac")
        mock_convert_file.return_value = [mock_result]

        result = shrink_media("/tmp/input.wav", 1000)
        self.assertEqual(result, "Shrink operation completed successfully. Output file generated at: /tmp/output.flac")
        mock_convert_file.assert_called_once_with(
            source=Path("/tmp/input.wav"),
            target_bytes=1000,
            root=None,
            output_dir=None
        )

    @patch('mcp_driver.media_shrinker.convert_file')
    def test_shrink_media_failure_no_output(self, mock_convert_file):
        """Test failure when conversion returns no output."""
        mock_convert_file.return_value = []
        result = shrink_media("/tmp/input.wav", 1000)
        self.assertEqual(result, "Shrink operation failed. See server logs for details.")

    @patch('mcp_driver.media_shrinker.convert_file')
    def test_shrink_media_exception(self, mock_convert_file):
        """Test failure when conversion raises an exception."""
        mock_convert_file.side_effect = Exception("Test Error")
        result = shrink_media("/tmp/input.wav", 1000)
        self.assertTrue(result.startswith("Shrink operation failed:"))
        self.assertIn("Test Error", result)

if __name__ == '__main__':
    unittest.main()
