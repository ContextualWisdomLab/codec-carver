## 2024-05-24 - CLI Arguments as UX
**Learning:** In headless or CLI-only applications, the command-line help interface serves as the primary UI. Missing help strings and lack of default value visibility severely impacts developer/user experience and accessibility.
**Action:** Always ensure `argparse` leverages `ArgumentDefaultsHelpFormatter` and that every argument has a descriptive `help` parameter to provide an intuitive "interface" for CLI tools.

## 2024-06-07 - Accessibility in CLI and Web Forms
**Learning:** Both CLI tools and simple web forms need explicit accessibility features. `argparse` needs `ArgumentDefaultsHelpFormatter` to act as a proper interface guide, and HTML form inputs require `<label>` elements with matching `for` and `id` attributes to be properly announced by screen readers.
**Action:** Always ensure CLI help text displays default values via `ArgumentDefaultsHelpFormatter` and always connect `<label>` elements to their inputs via `id` and `for` attributes in HTML templates.
## 2024-06-08 - Visual loading states and preventing double submission
**Learning:** Web forms that process large files take time, leaving users wondering if their click registered. This lack of feedback causes double submissions and confusion.
**Action:** Always provide immediate visual feedback upon form submission. Add an inline `onsubmit` handler to disable the submit button and change its text to "Processing...", and use `:disabled` and `:focus-visible` CSS pseudo-classes to ensure disabled states are styled and keyboard navigation is clear.

## 2024-05-20 - Form Input Accessibility with helper text
**Learning:** Adding helper text with `aria-describedby` combined with input constraints (`min`, `accept`) greatly improves form usability and prevents user errors before submission.
**Action:** Always pair complex inputs (like raw byte values or file uploads) with clear, accessible helper text and native HTML validation constraints.
