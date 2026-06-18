import subprocess
open("-help", "w").close()
res = subprocess.run(["ffprobe", "-v", "quiet", "-show_format", "-show_streams", "-help"], capture_output=True, text=True)
print(res.stdout[:100])
