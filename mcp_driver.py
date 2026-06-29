"""MCP server wrapper for Codec Carver media shrinking."""

from pathlib import Path
from mcp.server.fastmcp import FastMCP
import media_shrinker

mcp = FastMCP("Codec Carver")

@mcp.tool()
def shrink_media(source_path: str, output_dir: str, target_bytes: int = 2_000_000_000) -> str:
    """
    Shrink a media file to fit under a target size, preserving metadata and using FLAC/Opus.

    Args:
        source_path: Absolute or relative path to the input media file.
        output_dir: Path to the directory where the converted file will be saved.
        target_bytes: Maximum target size for the output file in bytes (default 2GB).

    Returns:
        A string summarizing the result of the conversion.
    """
    source = Path(source_path).resolve()
    out_dir = Path(output_dir).resolve()

    if not source.exists():
        return f"Error: Source file does not exist: {source}"

    out_dir.mkdir(parents=True, exist_ok=True)
    root = source.parent

    try:
        results = media_shrinker.convert_file(
            source=source,
            root=root,
            output_dir=out_dir,
            target_bytes=target_bytes,
        )

        output_messages = []
        for res in results:
            msg = f"Status: {res.status}"
            if res.output_path:
                msg += f", Output: {res.output_path}"
            if res.strategy:
                msg += f", Strategy: {res.strategy}"
            if res.message:
                msg += f", Details: {res.message}"
            output_messages.append(msg)

        if not output_messages:
             return "No conversion results generated."

        return "\n".join(output_messages)

    except Exception as e:
        return f"Conversion failed with error: {str(e)}"

if __name__ == "__main__":  # pragma: no cover
    mcp.run()
