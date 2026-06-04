💡 What
Added `ArgumentDefaultsHelpFormatter` to the `argparse.ArgumentParser` in `media_shrinker.py` and provided explicit `help` strings to all previously undocumented arguments (such as `--size-limit-bytes`, `--target-bytes`, etc.).

🎯 Why
For a CLI tool, the terminal output is the user interface. Before this change, running `python3 media_shrinker.py -h` showed an unhelpful list of flags without explanations or their default values. This update makes the interface much more intuitive, accessible, and self-documenting for end-users, aligning perfectly with UX principles for developer tools.

📸 Before/After
**Before:**
```
  --size-limit-bytes SIZE_LIMIT_BYTES
  --target-bytes TARGET_BYTES
  --max-duration-seconds MAX_DURATION_SECONDS
  --output-dir OUTPUT_DIR
```

**After:**
```
  --size-limit-bytes SIZE_LIMIT_BYTES
                        Size limit in bytes for source files (default:
                        2000000000)
  --target-bytes TARGET_BYTES
                        Target max size in bytes for each output (default:
                        1900000000)
  --max-duration-seconds MAX_DURATION_SECONDS
                        Max duration in seconds per output (default: 14400)
  --output-dir OUTPUT_DIR
                        Directory for generated output files (default:
                        under_2gb)
```

♿ Accessibility
Improves cognitive accessibility by not requiring users to guess or memorize the purpose and default behaviors of complex CLI flags.
