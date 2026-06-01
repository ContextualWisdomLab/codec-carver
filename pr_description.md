# Docker Deployment Support for SaaS

This PR introduces containerization support to easily orchestrate the `media_shrinker` SaaS web server and MCP driver.

### Features Added
1. **Dockerfile**: A container definition based on `python:3.12-slim` that handles installing necessary system dependencies (like `ffmpeg`), Python dependencies, and starts the FastAPI web server.
2. **docker-compose.yml**: A Compose configuration to easily spin up the web server on port `8000` with local volume mapping.
3. **README Documentation**: Updated instructions on how to start the SaaS locally using `docker-compose` and how to run the MCP server using `fastmcp`.
