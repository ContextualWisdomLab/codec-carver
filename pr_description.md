# MCP Driver and SaaS Web Integration

This PR introduces an MCP Driver and a Web SaaS interface for the `media_shrinker.py` core logic, as requested by the user.

### Features Added
1. **MCP Driver (`mcp_driver.py`)**: Utilizes `mcp.server.fastmcp.FastMCP` to wrap the `convert_file` function into a tool named `shrink_media`, enabling AI LLMs via MCP clients to interact with the media shrinking logic seamlessly.
2. **SaaS Web UI (`saas_web.py`)**: Built with FastAPI. It features a root endpoint returning an HTML UI for end-users to upload files, specify target byte constraints, and download the shrunk file directly via the browser. Safe file handling features are included (e.g. `shutil.copyfileobj` for large files without OOM issues and synchronous route handlers for CPU-bound tasks).
3. **Dependencies**: Added `requirements.txt` tracking `fastapi`, `uvicorn`, `python-multipart`, `mcp`, `aiofiles`, and `httpx`.
4. **Testing**: Integrated new test suites for both components (`tests/test_saas_web.py` and `tests/test_mcp_driver.py`) which use mocks to ensure proper internal logic handling.
