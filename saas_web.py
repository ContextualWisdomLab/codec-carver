"""FastAPI upload UI for shrinking one media file through Codec Carver."""

import json
import tempfile
import logging
import shutil
import zipfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import media_shrinker

app = FastAPI(title="Codec Carver SaaS")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 10 * 1024 * 1024
MAX_BATCH_FILES = 20
ALLOWED_UPLOAD_CONTENT_PREFIXES = ("audio/", "video/")


class RequestTooLarge(Exception):
    """Raised when streamed request bytes exceed the accepted upload envelope."""

    pass


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Reject declared or streamed request bodies above the service limit."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid Content-Length"})
        if declared_size < 0:
            return JSONResponse(status_code=400, content={"error": "Invalid Content-Length"})
        if declared_size > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"error": "Payload Too Large"})

    received = 0
    receive = request._receive

    async def limited_receive():
        """Count streamed request bytes before handing them to FastAPI."""

        nonlocal received
        message = await receive()
        if message.get("type") == "http.request":
            received += len(message.get("body", b""))
            if received > MAX_REQUEST_BYTES:
                raise RequestTooLarge
        return message

    request._receive = limited_receive
    try:
        return await call_next(request)
    except RequestTooLarge:
        return JSONResponse(status_code=413, content={"error": "Payload Too Large"})

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Attach conservative browser security headers to every response."""

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
logger = logging.getLogger(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Codec Carver SaaS</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; }
        .box { border: 1px solid #ccc; padding: 20px; border-radius: 8px; }
        button { padding: 10px 20px; background-color: #0056b3; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover:not(:disabled) { background-color: #004085; }
        button:disabled { background-color: #6c757d; cursor: not-allowed; }
        button:focus-visible, input:focus-visible { outline: 2px solid #004085; outline-offset: 2px; }
        .required-star { color: #dc3545; }
        .help-text { color: #6c757d; font-size: 0.85em; display: inline-block; margin-top: 4px; }
        .spinner { display: inline-block; width: 1em; height: 1em; vertical-align: -0.125em; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: spinner-border .75s linear infinite; margin-right: 8px; }
        @keyframes spinner-border { to { transform: rotate(360deg); } }
        .box { transition: background-color 0.2s, border-color 0.2s; }
        .box.dragover { background-color: #f8f9fa; border-color: #0056b3; border-style: dashed; }
        .preset-container { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
        .preset-btn { padding: 4px 8px; font-size: 0.85em; background-color: #e9ecef; color: #495057; border: 1px solid #ced4da; border-radius: 4px; cursor: pointer; }
        .preset-btn:hover { background-color: #dde2e6; color: #212529; }
    </style>
</head>
<body>
    <div class="box" id="drop-zone">
        <h2>Shrink Media File</h2>
        <form action="/shrink" method="post" enctype="multipart/form-data" id="shrink-form">
            <p>
                <label for="file">Media File: <span class="required-star" aria-hidden="true">*</span></label><br>
                <input type="file" id="file" name="file" accept="audio/*,video/*" aria-describedby="file_help file_size_preview" required onchange="updateFileSizePreview(this)">
                <br><span id="file_help" class="help-text">Select an audio or video file to shrink, or drag and drop it here.</span>
                <br><span id="file_size_preview" class="help-text" aria-live="polite" style="font-weight: bold; color: #0f6674;"></span>
            </p>
            <p>
                <label for="target_bytes">Target Bytes: <span class="required-star" aria-hidden="true">*</span></label><br>
                <input type="number" id="target_bytes" name="target_bytes" value="2000000000" min="1" aria-describedby="target_bytes_help target_bytes_preview preset_buttons_container" required>
                <br><span id="target_bytes_help" class="help-text">Maximum allowed file size in bytes (e.g., 2000000000 for ~1.86 GiB)</span>
                <br><span id="target_bytes_preview" class="help-text" aria-live="polite" style="font-weight: bold; color: #1e7e34;">1.86 GiB</span>
                <div id="preset_buttons_container" class="preset-container">
                    <button type="button" class="preset-btn" onclick="setTargetBytes(26214400)">25 MiB</button>
                    <button type="button" class="preset-btn" onclick="setTargetBytes(104857600)">100 MiB</button>
                    <button type="button" class="preset-btn" onclick="setTargetBytes(524288000)">500 MiB</button>
                    <button type="button" class="preset-btn" onclick="setTargetBytes(1073741824)">1 GiB</button>
                </div>
            </p>
            <button type="submit" id="submit-btn">Upload and Shrink</button>
        </form>
        <script>
            const MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;
            function formatBinaryBytes(value) {
                const units = ['B', 'KiB', 'MiB', 'GiB'];
                let size = value;
                let unit = 0;
                while (size >= 1024 && unit < units.length - 1) {
                    size = size / 1024;
                    unit += 1;
                }
                return unit === 0 ? size + ' ' + units[unit] : size.toFixed(2) + ' ' + units[unit];
            }
            function setTargetBytes(bytes) {
                const input = document.getElementById('target_bytes');
                input.value = bytes;
                input.dispatchEvent(new Event('input'));
            }

            function updateFileSizePreview(input) {
                const file = input.files[0];
                const preview = document.getElementById('file_size_preview');
                input.setCustomValidity('');
                input.removeAttribute('aria-invalid');
                preview.style.color = '#0f6674';
                if (!file) {
                    preview.innerText = '';
                    return;
                }
                const text = formatBinaryBytes(file.size);
                if (file.size > MAX_UPLOAD_BYTES) {
                    input.setCustomValidity('File exceeds 5 GiB limit.');
                    input.setAttribute('aria-invalid', 'true');
                    preview.innerText = 'Selected file size: ' + text + ' (exceeds 5 GiB limit)';
                    preview.style.color = '#dc3545';
                    return;
                }
                preview.innerText = 'Selected file size: ' + text;
            }

            document.getElementById('target_bytes').addEventListener('input', function() {
                const val = parseInt(this.value, 10);
                const preview = document.getElementById('target_bytes_preview');
                this.setCustomValidity('');
                this.removeAttribute('aria-invalid');
                preview.style.color = '#1e7e34';

                if (isNaN(val) || val <= 0) {
                    preview.innerText = 'Must be greater than 0.';
                    preview.style.color = '#dc3545';
                    this.setCustomValidity('Must be greater than 0.');
                    this.setAttribute('aria-invalid', 'true');
                } else {
                    preview.innerText = formatBinaryBytes(val);
                }
            });

            document.getElementById('shrink-form').addEventListener('submit', function() {
                const btn = document.getElementById('submit-btn');
                setTimeout(() => {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span>Processing...';
                    btn.setAttribute('aria-busy', 'true');
                }, 10);
            });

        const dropZone = document.getElementById('drop-zone');
        const fileInput = document.getElementById('file');
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, preventDefaults, false);
            document.body.addEventListener(eventName, preventDefaults, false);
        });
        function preventDefaults (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
        });
        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
        });
        dropZone.addEventListener('drop', (e) => {
            let dt = e.dataTransfer;
            let files = dt.files;
            if (files.length) {
                fileInput.files = files;
                updateFileSizePreview(fileInput);
            }
        }, false);
        </script>
    </div>
    <div class="box" style="margin-top: 20px;">
        <h2>Shrink Multiple Files</h2>
        <form action="/shrink-batch" method="post" enctype="multipart/form-data" id="shrink-batch-form">
            <p>
                <label for="batch_files">Media Files (up to 20): <span class="required-star" aria-hidden="true">*</span></label><br>
                <input type="file" id="batch_files" name="files" accept="audio/*,video/*" multiple aria-describedby="batch_files_help" required>
                <br><span id="batch_files_help" class="help-text">Select several audio or video files. You get back one zip with every output plus a results.json manifest.</span>
            </p>
            <p>
                <label for="batch_target_bytes">Target Bytes (per file): <span class="required-star" aria-hidden="true">*</span></label><br>
                <input type="number" id="batch_target_bytes" name="target_bytes" value="2000000000" min="1" aria-describedby="batch_target_bytes_help" required>
                <br><span id="batch_target_bytes_help" class="help-text">Maximum allowed size in bytes for each output file</span>
            </p>
            <button type="submit" id="batch-submit-btn">Upload and Shrink Batch</button>
        </form>
    </div>
</body>
</html>
"""

def cleanup_temp_dir(temp_dir_path: Path):
    """Clean up the temporary directory after the response is sent."""
    if temp_dir_path.exists():
        shutil.rmtree(temp_dir_path, ignore_errors=True)


@app.get("/", response_class=HTMLResponse)
async def get_ui():
    """Return the single-page upload form."""

    return HTML_TEMPLATE


@app.post("/shrink")
def shrink_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_bytes: int = Form(2_000_000_000)
):
    """Persist an uploaded media file, shrink it, and return the generated file."""

    if target_bytes <= 0:
        return {"error": "Invalid target_bytes value. Must be greater than 0."}

    if not file.filename:
        return {"error": "No file uploaded or filename missing"}

    # Create a temporary directory that will hold the input and output
    try:
        temp_dir = tempfile.mkdtemp(prefix="codec_carver_")
        temp_dir_path = Path(temp_dir)
    except Exception:
        logger.exception("Failed to create upload workspace")
        return {"error": "Upload processing failed"}

    try:
        # Setup paths
        input_dir = temp_dir_path / "input"
        output_dir = temp_dir_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        # Save the uploaded file
        safe_filename = Path(file.filename).name
        if not safe_filename or safe_filename in (".", ".."):
            safe_filename = "upload.tmp"

        source_path = input_dir / safe_filename
        bytes_written = 0
        with open(source_path, "wb") as f:
            while chunk := file.file.read(1024 * 1024):  # 1 MB chunks
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise ValueError("File exceeds maximum allowed upload size")
                f.write(chunk)
    except Exception:
        cleanup_temp_dir(temp_dir_path)
        logger.exception("Failed to prepare uploaded media")
        return {"error": "Upload processing failed"}

    # Process the file using media_shrinker
    try:
        results = media_shrinker.convert_file(
            source=source_path,
            root=input_dir,
            output_dir=output_dir,
            target_bytes=target_bytes,
        )

        # Determine the generated output file.
        # For simplicity, returning the first output file found.
        # Handling multiple outputs (e.g. from splitting) would require zipping in a real scenario.
        if results and results[0].output_path and results[0].output_path.exists():
             output_file_path = results[0].output_path
             # Schedule cleanup after response
             background_tasks.add_task(cleanup_temp_dir, temp_dir_path)
             return FileResponse(
                 path=output_file_path,
                 filename=output_file_path.name,
                 media_type="application/octet-stream"
             )
        else:
            background_tasks.add_task(cleanup_temp_dir, temp_dir_path)
            logger.error("Processing produced no output: %r", results)
            return {"error": "Processing failed or no output generated"}

    except Exception:
        cleanup_temp_dir(temp_dir_path)
        logger.exception("Media processing failed")
        return {"error": "Upload processing failed"}

def _safe_upload_name(filename):
    """Return a directory-free filename for an upload, with a safe fallback.

    Strips any client-supplied directory components and substitutes
    ``upload.tmp`` when the remaining name is empty or a dot entry, so a
    hostile filename can never escape the request's temp workspace.
    """

    safe_filename = Path(filename or "").name
    if not safe_filename or safe_filename in (".", ".."):
        safe_filename = "upload.tmp"
    return safe_filename


def _save_upload_stream(upload, destination: Path):
    """Stream one uploaded file to ``destination`` in 1 MB chunks.

    Raises ``ValueError`` as soon as the written bytes exceed
    ``MAX_UPLOAD_BYTES`` so oversized uploads are aborted early instead of
    filling the disk. Mirrors the save pattern used by the ``/shrink``
    endpoint.
    """

    bytes_written = 0
    with open(destination, "wb") as f:
        while chunk := upload.file.read(1024 * 1024):  # 1 MB chunks
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_BYTES:
                raise ValueError("File exceeds maximum allowed upload size")
            f.write(chunk)


@app.post("/shrink-batch")
def shrink_media_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(default=[]),
    target_bytes: int = Form(2_000_000_000),
):
    """Shrink several uploaded media files and return one zip archive.

    Accepts up to ``MAX_BATCH_FILES`` audio/video uploads, converts each one
    with :func:`media_shrinker.convert_file`, and responds with a single
    ``ZIP_STORED`` archive containing every successful output plus a
    ``results.json`` manifest describing the per-file outcome (status,
    output name, output size, and error message when a file failed).

    Per-file failures are recorded in the manifest and never abort the rest
    of the batch. The whole request body remains bounded by the service-wide
    request size middleware, and each individual file is additionally capped
    at ``MAX_UPLOAD_BYTES``. The temp workspace is deleted after the response
    is sent.
    """

    if target_bytes <= 0:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid target_bytes value. Must be greater than 0."},
        )

    if not files:
        return JSONResponse(status_code=400, content={"error": "No files uploaded"})

    if len(files) > MAX_BATCH_FILES:
        return JSONResponse(
            status_code=400,
            content={"error": f"Too many files. Maximum is {MAX_BATCH_FILES} files per batch."},
        )

    try:
        temp_dir_path = Path(tempfile.mkdtemp(prefix="codec_carver_batch_"))
    except Exception:
        logger.exception("Failed to create batch upload workspace")
        return JSONResponse(status_code=500, content={"error": "Upload processing failed"})

    workspace_root = temp_dir_path.resolve()
    manifest = []
    zip_path = temp_dir_path / "codec_carver_batch.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for index, upload in enumerate(files):
                safe_filename = _safe_upload_name(upload.filename)
                entry = {
                    "index": index,
                    "filename": safe_filename,
                    "status": "error",
                    "output_name": None,
                    "output_bytes": None,
                    "error": None,
                }
                manifest.append(entry)

                content_type = upload.content_type or ""
                if not content_type.startswith(ALLOWED_UPLOAD_CONTENT_PREFIXES):
                    entry["error"] = "Unsupported content type. Only audio/* and video/* uploads are allowed."
                    continue

                # Each upload gets its own input/output directories so that
                # duplicate filenames in one batch can never collide.
                input_dir = temp_dir_path / f"input_{index}"
                output_dir = temp_dir_path / f"output_{index}"
                try:
                    input_dir.mkdir()
                    output_dir.mkdir()
                    source_path = input_dir / safe_filename
                    _save_upload_stream(upload, source_path)
                except Exception:
                    logger.exception("Failed to prepare batch upload #%d", index)
                    entry["error"] = "Upload processing failed"
                    continue

                try:
                    results = media_shrinker.convert_file(
                        source=source_path,
                        root=input_dir,
                        output_dir=output_dir,
                        target_bytes=target_bytes,
                    )
                except Exception:
                    logger.exception("Batch media processing failed for upload #%d", index)
                    entry["error"] = "Upload processing failed"
                    continue

                if not (results and results[0].output_path):
                    logger.error("Batch processing produced no output for upload #%d: %r", index, results)
                    entry["error"] = "Processing failed or no output generated"
                    continue

                output_path = Path(results[0].output_path).resolve()
                # Never serve files outside this request's temp workspace.
                if not (output_path.is_file() and output_path.is_relative_to(workspace_root)):
                    logger.error("Batch output for upload #%d is missing or outside the workspace", index)
                    entry["error"] = "Processing failed or no output generated"
                    continue

                arcname = f"{index + 1:02d}_{output_path.name}"
                archive.write(output_path, arcname=arcname)
                entry["status"] = "ok"
                entry["output_name"] = arcname
                entry["output_bytes"] = output_path.stat().st_size

            archive.writestr(
                "results.json",
                json.dumps({"target_bytes": target_bytes, "results": manifest}, indent=2),
            )
    except Exception:
        cleanup_temp_dir(temp_dir_path)
        logger.exception("Failed to build batch archive")
        return JSONResponse(status_code=500, content={"error": "Upload processing failed"})

    background_tasks.add_task(cleanup_temp_dir, temp_dir_path)
    return FileResponse(
        path=zip_path,
        filename="codec_carver_batch.zip",
        media_type="application/zip",
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
