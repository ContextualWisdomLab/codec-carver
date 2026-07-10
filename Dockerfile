# Codec Carver web service.
# Build:  docker build -t codec-carver .
# Run:    docker run -p 8000:8000 codec-carver
# Pinned by digest for reproducible, supply-chain-safe builds (python:3.12-slim).
FROM python:3.12-slim@sha256:86d3e4424d5e963e60594a3a6b4d597cc4d41f5152fe67a97a40dca9ea092475

# ffmpeg/ffprobe are required at runtime for probing and conversion.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md requirements-lock.txt ./
COPY media_shrinker.py saas_web.py mcp_driver.py ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check --require-hashes -r requirements-lock.txt

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Liveness: the FastAPI app serves the upload UI at "/".
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status==200 else 1)"

CMD ["uvicorn", "saas_web:app", "--host", "0.0.0.0", "--port", "8000"]
