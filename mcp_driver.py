"""FastMCP driver for Media Shrinker."""
from mcp.server.fastmcp import FastMCP
from pathlib import Path
import media_shrinker

# Initialize FastMCP server
mcp = FastMCP("codec-carver")

@mcp.tool()
def shrink_media(source_path: str, target_bytes: int) -> str:
    """
    Shrink a media file to a target size using Codec Carver.

    Args:
        source_path: The absolute path to the input media file.
        target_bytes: The desired maximum size of the output file in bytes.

    Returns:
        A string describing the result of the operation, including the output path if successful.
    """
    try:
        results = media_shrinker.convert_file(
            source=Path(source_path),
            target_bytes=target_bytes,
            root=None,
            output_dir=None
        )

        if not results:
            return "Shrink operation failed. See server logs for details."

        return f"Shrink operation completed successfully. Output file generated at: {results[0].output_path}"

    except Exception as e:
        return f"Shrink operation failed: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport='stdio')
