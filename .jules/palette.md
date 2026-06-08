## 2024-05-24 - CLI Arguments as UX
**Learning:** In headless or CLI-only applications, the command-line help interface serves as the primary UI. Missing help strings and lack of default value visibility severely impacts developer/user experience and accessibility.
**Action:** Always ensure `argparse` leverages `ArgumentDefaultsHelpFormatter` and that every argument has a descriptive `help` parameter to provide an intuitive "interface" for CLI tools.

## 2024-06-07 - Accessibility in CLI and Web Forms
**Learning:** Both CLI tools and simple web forms need explicit accessibility features. `argparse` needs `ArgumentDefaultsHelpFormatter` to act as a proper interface guide, and HTML form inputs require `<label>` elements with matching `for` and `id` attributes to be properly announced by screen readers.
**Action:** Always ensure CLI help text displays default values via `ArgumentDefaultsHelpFormatter` and always connect `<label>` elements to their inputs via `id` and `for` attributes in HTML templates.
