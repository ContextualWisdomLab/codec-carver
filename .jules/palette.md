## 2024-05-31 - Expose CLI Default Arguments Automatically
**Learning:** For CLI tools built in Python, the help menu acts as the primary user interface. Hidden default values create significant UX friction by forcing users to consult external documentation or guess behavior.
**Action:** Always configure `argparse.ArgumentParser` with `formatter_class=argparse.ArgumentDefaultsHelpFormatter` to automatically expose default values in the `--help` output, improving transparency and accessibility.
