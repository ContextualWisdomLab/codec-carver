# Codec Carver web service.
# Build:  docker build -t codec-carver .
# Run:    docker run -p 8000:8000 codec-carver
FROM python:3.12-slim

# ffmpeg/ffprobe are required at runtime for probing and conversion.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY media_shrinker.py saas_web.py mcp_driver.py ./
RUN pip install --no-cache-dir ".[web]"

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "saas_web:app", "--host", "0.0.0.0", "--port", "8000"]
