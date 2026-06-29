from pathlib import Path

source_path = Path("-foo.wav")
resolved = source_path.resolve()
print("resolved:", resolved)
