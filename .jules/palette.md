## 2024-07-12 - Intercepting batch form submissions for testing visual loading states
**Learning:** Extending the learning from 2024-06-13, intercepting form submissions using `e.preventDefault()` via `page.evaluate()` is essential for capturing screenshot and video evidence of loading states (e.g., button disabling, spinner appearing) on forms like batch upload where the submission would normally reload the page or download an archive.
**Action:** When testing visual loading states with Playwright, always inject an event listener using `page.evaluate()` to call `e.preventDefault()` on the form's `submit` event to freeze the UI in its loading state for verification.

## 2024-07-12 - Asynchronous button disabling for form submission
**Learning:** Disabling a submit button synchronously inside a `submit` event listener can sometimes cancel the submission entirely in certain browsers or frameworks.
**Action:** Always wrap the logic that disables the submit button and updates its UI (like adding a loading spinner) inside a short `setTimeout` (e.g., 10ms) within the `submit` event listener to ensure the browser registers the form submission correctly.
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

## 2026-06-10 - Add inline form helpers and client-side validation
**Learning:** Combining aria-describedby for helper text and aria-hidden on visual required indicators improves screen reader clarity while providing necessary visual cues to sighted users.
**Action:** Always pair visible required markers with aria-hidden, relying on the native required attribute for semantics, and link helper text with aria-describedby.
## 2024-05-24 - Dynamic Human-Readable File Size Preview
**Learning:** Users often struggle to conceptualize large numbers in bytes (e.g., 2000000000), leading to magnitude errors. Providing a live, ARIA-announced preview in familiar units (MB, GB) right next to the input drastically improves confidence and prevents submission mistakes.
**Action:** Always pair raw byte inputs with a dynamic, human-readable preview using an `aria-live` region.

## 2024-06-12 - Baseline HTML Accessibility and Responsiveness
**Learning:** Missing `lang="en"` causes screen readers to struggle with pronunciation, and missing viewport meta tags cause mobile devices to zoom out uncomfortably, breaking the responsive CSS.
**Action:** Always include `<html lang="en">` and `<meta name="viewport" content="width=device-width, initial-scale=1.0">` in raw HTML templates for baseline a11y and mobile UX.

## 2024-06-13 - Intercepting form submissions for testing visual loading states
**Learning:** When using Playwright to verify UI changes involving form submissions that trigger file downloads or navigate away from the page context, the page context may close or hang before the screenshot can capture visual states (like loading spinners).
**Action:** When using Playwright to verify UI changes involving form submissions that trigger file downloads or navigate away from the page context, explicitly inject a script to intercept the `submit` event and call `e.preventDefault()`. This prevents the browser from discarding the current DOM state or hanging on the download, allowing reliable capture of transitional states (e.g., loading spinners) and screenshots.
## 2024-06-14 - Add dynamic human-readable file size preview to file upload
**Learning:** In simple web forms without React/Vue, inline Javascript `onchange` events can provide essential dynamic accessibility feedback.
**Action:** Always pair raw file upload inputs with a dynamic, human-readable file size preview using an `aria-live` region, accessible via `aria-describedby`.
## 2026-06-21 - Accessible Form Validation
**Learning:** When using custom JS validation, dynamically toggling `aria-invalid='true'` in tandem with `setCustomValidity()` provides critical feedback to screen readers that isn't always reliably conveyed by custom validity alone.
**Action:** Always sync `aria-invalid` state with JS validation logic for screen reader users.
## 2024-06-25 - Expanding Drop Zones for File Inputs
**Learning:** Tiny file input buttons are hard targets. Expanding the drop zone to the entire parent container (and adding a clear `.dragover` visual state) drastically improves the drag-and-drop experience.
**Action:** Always make entire form containers accept dropped files when possible, rather than relying solely on the native file input element.
## 2026-06-23 - Improve Error Message Clarity
**Learning:** Added inline visual feedback to the 'target_bytes' input field for invalid inputs (e.g., negative or zero values) provides immediate context to the user. I saw the empty text in preview on invalid inputs in the UI test screenshots and in the code, and realized it would be better UX to display the error text in the preview span with red styling, rather than leaving it empty.
**Action:** Add descriptive innerText and red color styling to the preview element on validation failure to enhance error visibility.

## 2024-06-29 - UI 색상 대비(WCAG AA) 개선
**Learning:** `#007bff`, `#17a2b8`, `#28a745` 등 기본 Bootstrap 색상들은 하얀 배경에서 사용할 때 종종 WCAG AA 색상 대비 가이드라인을 통과하지 못하며, 이는 시각 장애가 있는 사용자들의 가독성을 떨어뜨립니다.
**Action:** 충분한 명암비를 보장하기 위해 기본 Bootstrap 색상을 어둡고 접근성 높은 대안 색상(예: 기본 색상은 `#0056b3`, 정보 색상은 `#0f6674`, 성공 색상은 `#1e7e34`)으로 교체하십시오.

## 2024-06-30 - Quick Preset Buttons for Raw Inputs
**Learning:** Large raw byte inputs create high cognitive load and increase magnitude errors. Providing accessible quick preset buttons allows users to quickly select common values with confidence, reducing errors and reliance on manual typing.
**Action:** Add quick preset buttons for common values near raw inputs (especially bytes), ensuring they are accessible via keyboard and properly associated with `aria-describedby`.
## 2024-07-08 - Accessible Toggle Button Groups and Event Delegation
**Learning:** Using `aria-describedby` to associate a container of quick preset buttons with an input causes excessive screen reader verbosity. Grouping buttons semantically with `role="group"` and `aria-label` is better. Also, relying on visual cues alone for active state in preset buttons is inaccessible; they must use `aria-pressed` to convey toggle state. Finally, event delegation and dataset attributes reduce DOM clutter and inline JavaScript, improving maintainability and removing duplicate data.
**Action:** When implementing grouped option buttons, use `role="group"` with an `aria-label` on the container, implement `aria-pressed` for toggle states, and use event delegation combined with `data-*` attributes instead of inline `onclick` handlers.

## 2024-07-10 - Preset buttons active state with `aria-pressed`
**Learning:** When implementing preset or toggle buttons in UI forms, using `aria-pressed` attributes dynamically managed by JavaScript is essential to track active states. This should always be paired with a corresponding CSS rule (e.g., `[aria-pressed="true"]`) to provide clear visual feedback, and the active state should be cleared when the user manually modifies the associated input field (distinguishable via `e.isTrusted` on the event).
**Action:** Always implement `aria-pressed` with paired CSS for preset toggle buttons, and use `e.isTrusted` to properly reset states on manual user input.

## 2024-05-24 - Visual Feedback for aria-invalid
**Learning:** Screen readers announce `aria-invalid="true"`, but sighted users need visual cues when form validation fails dynamically on the client side.
**Action:** When setting `aria-invalid="true"` via JS, always pair it with a CSS rule like `input[aria-invalid="true"] { border-color: #dc3545; outline: 2px solid #dc3545; }` for reliable visual feedback.
## 2024-05-19 - Support Drag-and-Drop for Multiple Files Upload
**Learning:** Missing drop zone support for secondary forms in an application restricts usability, as users naturally expect the same affordances everywhere.
**Action:** Expanded the drag-and-drop container zone logic to reuse event handlers across both single-file and multi-file input zones.

## 2024-07-12 - Inline validation for batch file inputs
**Learning:** Selecting too many files in a batch input without immediate feedback causes frustration and forces users to discover errors only upon form submission. Validating the file limit client-side and showing an error message inline improves user experience.
**Action:** When using `multiple` file inputs, always implement an `onchange` event listener to validate the file count and file size limits on the client side, using `setCustomValidity` and `aria-invalid` to provide immediate inline feedback before submission.
