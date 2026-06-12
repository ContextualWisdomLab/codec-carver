import tempfile
import logging
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, FileResponse
import media_shrinker

app = FastAPI(title="Codec Carver SaaS")

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
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
        button { padding: 10px 20px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover:not(:disabled) { background-color: #0056b3; }
        button:disabled { background-color: #6c757d; cursor: not-allowed; }
        button:focus-visible, input:focus-visible { outline: 2px solid #0056b3; outline-offset: 2px; }
        .required-star { color: #dc3545; }
        .help-text { color: #6c757d; font-size: 0.85em; display: inline-block; margin-top: 4px; }
    </style>
</head>
<body>
    <div class="box">
        <h2>Shrink Media File</h2>
        <form action="/shrink" method="post" enctype="multipart/form-data" id="shrink-form">
            <p>
                <label for="file">Media File: <span class="required-star" aria-hidden="true">*</span></label><br>
                <input type="file" id="file" name="file" accept="audio/*,video/*" aria-describedby="file_help" required>
                <br><span id="file_help" class="help-text">Select an audio or video file to shrink.</span>
            </p>
            <p>
                <label for="target_bytes">Target Bytes: <span class="required-star" aria-hidden="true">*</span></label><br>
                <input type="number" id="target_bytes" name="target_bytes" value="2000000000" min="1" aria-describedby="target_bytes_help target_bytes_preview" required oninput="const val = parseInt(this.value, 10); const preview = document.getElementById('target_bytes_preview'); if (isNaN(val) || val <= 0) { preview.innerText = ''; } else if (val < 1000) { preview.innerText = val + ' B'; } else if (val < 1000000) { preview.innerText = (val / 1000).toFixed(2) + ' KB'; } else if (val < 1000000000) { preview.innerText = (val / 1000000).toFixed(2) + ' MB'; } else { preview.innerText = (val / 1000000000).toFixed(2) + ' GB'; }">
                <br><span id="target_bytes_help" class="help-text">Maximum allowed file size in bytes (e.g., 2000000000 for ~2GB)</span>
                <br><span id="target_bytes_preview" class="help-text" aria-live="polite" style="font-weight: bold; color: #28a745;">2.00 GB</span>
            </p>
            <button type="submit" id="submit-btn">Upload and Shrink</button>
        </form>
        <script>
            document.getElementById('shrink-form').addEventListener('submit', function() {
                const btn = document.getElementById('submit-btn');
                setTimeout(() => {
                    btn.disabled = true;
                    btn.innerText = 'Processing...';
                    btn.setAttribute('aria-busy', 'true');
                }, 10);
            });
        </script>
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
    return HTML_TEMPLATE


@app.post("/shrink")
def shrink_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_bytes: int = Form(2_000_000_000)
):
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
        with open(source_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
