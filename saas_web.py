import tempfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Form
from fastapi.responses import HTMLResponse, FileResponse
import media_shrinker

app = FastAPI(title="Codec Carver SaaS")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Codec Carver SaaS</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; }
        .box { border: 1px solid #ccc; padding: 20px; border-radius: 8px; }
        button { padding: 10px 20px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
        button:focus-visible, input:focus-visible { outline: 2px solid #0056b3; outline-offset: 2px; }
    </style>
</head>
<body>
    <div class="box">
        <h2>Shrink Media File</h2>
        <form action="/shrink" method="post" enctype="multipart/form-data">
            <p>
                <label for="file">Media File:</label><br>
                <input type="file" id="file" name="file" required>
            </p>
            <p>
                <label for="target_bytes">Target Bytes:</label><br>
                <input type="number" id="target_bytes" name="target_bytes" value="2000000000" required>
            </p>
            <button type="submit">Upload and Shrink</button>
        </form>
    </div>
</body>
</html>
"""

def cleanup_temp_dir(temp_dir_path: Path):
    """Clean up the temporary directory after the response is sent."""
    import shutil
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
    # Create a temporary directory that will hold the input and output
    temp_dir = tempfile.mkdtemp(prefix="codec_carver_")
    temp_dir_path = Path(temp_dir)

    # Setup paths
    input_dir = temp_dir_path / "input"
    output_dir = temp_dir_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    # Save the uploaded file
    safe_filename = Path(file.filename).name
    source_path = input_dir / safe_filename
    import shutil
    with open(source_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

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
            return {"error": "Processing failed or no output generated", "details": str(results)}

    except Exception as e:
        cleanup_temp_dir(temp_dir_path)
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
