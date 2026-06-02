
## 2024-06-02 - CLI Argument Defaults Help Formatter
**Learning:** For CLI tools, argument help text and default value formats (e.g. `ArgumentDefaultsHelpFormatter`) serve as the UI. Adding them significantly improves discoverability and usability without changing core logic.
**Action:** Always check if a script uses `argparse` without `ArgumentDefaultsHelpFormatter` and whether key arguments have `help=` descriptions, as this is a quick, high-impact micro-UX win.
