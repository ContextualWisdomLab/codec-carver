## 2025-06-01 - Default Argument Help Texts Make a UI More Usable
**Learning:** For command-line interfaces (CLI), missing help texts and omitting the default value of an argument leads to friction and confusion, forcing users to trial-and-error to understand system behavior.
**Action:** When working on CLI tools in Python, prefer using `argparse.ArgumentDefaultsHelpFormatter` to automatically include default values in the help text and always provide descriptions for standard arguments like thresholds or directories.
