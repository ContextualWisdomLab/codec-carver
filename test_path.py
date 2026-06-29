from pathlib import Path

source_path = Path("../../../etc/passwd")
output_dir = Path("/tmp/output")
relative_source = Path(source_path.name) if source_path.is_absolute() else source_path
out = output_dir / relative_source.with_name(f"{relative_source.name}.flac")
print("out:", out)
print("resolved:", out.resolve())
