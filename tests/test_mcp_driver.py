import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import types


class _FakeFastMCP:
    def __init__(self, name):
        self.name = name

    def tool(self):
        return lambda func: func

    def run(self):
        return None


def _install_fake_mcp():
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = _FakeFastMCP
    server_module.fastmcp = fastmcp_module
    mcp_module.server = server_module
    sys.modules.setdefault("mcp", mcp_module)
    sys.modules.setdefault("mcp.server", server_module)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp_module)


try:
    from mcp_driver import shrink_media

    _HAS_MCP = True
except ImportError as exc:
    if exc.name not in {"mcp", "mcp.server", "mcp.server.fastmcp"}:
        raise
    _install_fake_mcp()
    from mcp_driver import shrink_media

    _HAS_MCP = True

from media_shrinker import ConversionResult


@unittest.skipUnless(_HAS_MCP, "mcp not installed (optional integration dependency)")
class TestMCPDriver(unittest.TestCase):

    @patch("mcp_driver.media_shrinker.convert_file")
    def test_shrink_media_success(self, mock_convert_file):
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
        result_str = shrink_media("/path/does/not/exist.wav", "/tmp/out")
        self.assertIn("Error: Source file does not exist", result_str)

    @patch("mcp_driver.media_shrinker.convert_file")
    def test_shrink_media_exception(self, mock_convert_file):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            source_file = temp_dir_path / "source.wav"
            source_file.touch()
            output_dir = temp_dir_path / "output"

            mock_convert_file.side_effect = Exception("Test FFmpeg error")

            result_str = shrink_media(str(source_file), str(output_dir))

            self.assertIn("Conversion failed with error: Test FFmpeg error", result_str)

    @patch("mcp_driver.media_shrinker.convert_file")
    def test_shrink_media_handles_empty_result(self, mock_convert_file):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            source_file = temp_dir_path / "source.wav"
            source_file.touch()

            mock_convert_file.return_value = []

            result_str = shrink_media(str(source_file), str(temp_dir_path / "output"))

            self.assertEqual(result_str, "No conversion results generated.")

if __name__ == '__main__':
    unittest.main()
