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
