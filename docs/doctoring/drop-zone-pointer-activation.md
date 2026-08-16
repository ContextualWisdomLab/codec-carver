# Drop-zone pointer activation

## Decision

The Codec Carver upload page treats each `.box` container as a larger pointer
target for choosing files. Clicking empty space in `#drop-zone` or
`#batch-drop-zone` opens the matching native file picker. Clicks that originate
inside an `input`, `button`, or `label` (including a nested `span` such as the
required-star marker) do not synthesize a second picker activation.

Keyboard and assistive-technology users continue to use the native file input
and its associated label. The containers are landmarks (`role="region"` with
distinct `aria-label` values), not buttons, so the form semantics stay intact.

Listener registration waits for `DOMContentLoaded`. The first inline script is
parsed before `#batch-drop-zone` exists; looking up batch controls at parse time
throws and leaves the click contract unregistered.

## Buyer-visible next action

1. Open the upload page.
2. Click empty space in the single-file or batch card, or drag files onto it.
3. Confirm the live size preview, then submit.

## Technical basis

Larger pointing targets reduce movement time and miss rate, which is the
practical reading of Fitts's law for this form (Fitts, 1954; MacKenzie, 1992).
WCAG 2.2 Success Criterion 2.5.8 asks for a minimum target size; expanding the
card is a pointer convenience, not a replacement for the native control
(World Wide Web Consortium, 2023). WAI-ARIA 1.2 region landmarks name the two
upload areas without turning the card into a composite widget (World Wide Web
Consortium, 2021). Keyboard operability remains on the native control
(Success Criterion 2.1.1).

## Verification and rollback

- Source assertions require `DOMContentLoaded`, two `closest('input, button,
  label')` guards, and `fileInput.click()`.
- `tests/test_saas_ui_contract.py` executes the generated script in a Node DOM
  harness and requires exactly one single-file picker click and one batch
  picker click after empty-space activation, with no extra clicks from
  `INPUT`, `BUTTON`, `LABEL`, or a `SPAN` nested in a `LABEL`.
- Roll back by removing only the click listeners. Do not delete the
  `DOMContentLoaded` boundary or the landmark attributes in the same edit.

## References

Fitts, P. M. (1954). The information capacity of the human motor system in
controlling the amplitude of movement. *Journal of Experimental Psychology,
47*(6), 381–391. https://doi.org/10.1037/h0055392

MacKenzie, I. S. (1992). Fitts' law as a research and design tool in
human-computer interaction. *Human-Computer Interaction, 7*(1), 91–139.
https://doi.org/10.1207/s15327051hci0701_3

World Wide Web Consortium. (2021). *Accessible rich internet applications
(WAI-ARIA) 1.2*. https://www.w3.org/TR/wai-aria-1.2/

World Wide Web Consortium. (2023). *Web content accessibility guidelines
(WCAG) 2.2*. https://www.w3.org/TR/WCAG22/
