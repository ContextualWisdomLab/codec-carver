# Design tokens

Repeated SaaS upload surfaces share one `:root` token set in `saas_web.py`.
Change a token once; do not re-hardcode the same hex on the next card.

| Token | Role | Next action |
| --- | --- | --- |
| `--cc-color-action` | Primary submit and pressed preset | Use for the control the buyer should click next |
| `--cc-color-action-hover` | Hover and focus ring | Keep focus visible on the same action color family |
| `--cc-color-disabled` | Busy submit | Show that another click will not start a second job |
| `--cc-color-help` | Helper copy | Tell the buyer to click the card or drag a file |
| `--cc-color-danger` | Required star and invalid input | Fix the field before submit |
| `--cc-color-info` | File-size preview | Confirm the selected file is the intended one |
| `--cc-color-success` | Target-size preview | Confirm the output cap before upload |
| `--cc-color-border` / `--cc-radius-box` | Upload card chrome | Treat the whole card as the drop/click target |
| `--cc-color-preset*` | Target-size shortcuts | Pick a common cap without typing bytes |

Storybook is inventory-only until this page is split into importable
components. See [`docs/storybook-inventory.md`](storybook-inventory.md).
