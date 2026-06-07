## 2024-06-07 - Accessibility in CLI and Web Forms
**Learning:** Both CLI tools and simple web forms need explicit accessibility features. `argparse` needs `ArgumentDefaultsHelpFormatter` to act as a proper interface guide, and HTML form inputs require `<label>` elements with matching `for` and `id` attributes to be properly announced by screen readers.
**Action:** Always ensure CLI help text displays default values via `ArgumentDefaultsHelpFormatter` and always connect `<label>` elements to their inputs via `id` and `for` attributes in HTML templates.
