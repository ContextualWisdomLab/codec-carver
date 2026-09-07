# Storybook inventory

The upload UI is still one FastAPI HTML template. A Storybook package is not
installed here because it would add a Node toolchain to a Python stdlib-first
repository. This inventory is the module boundary to extract when the page is
split.

| Object | Occurrences | Tokens | Buyer next action |
| --- | --- | --- | --- |
| Upload card / drop zone | Single + batch | `--cc-color-border`, `--cc-radius-box`, `--cc-space-box` | Click the card or drag files onto it |
| File input + label + help | Single + batch | `--cc-color-help`, `--cc-color-danger` | Choose audio/video, or use the card |
| Size preview live region | File and target bytes | `--cc-color-info`, `--cc-color-success` | Confirm size before upload |
| Preset button group | Single + batch | `--cc-color-preset*` | Pick 25 MiB, 100 MiB, 500 MiB, or 1 GiB |
| Submit + busy spinner | Single + batch | `--cc-color-action`, `--cc-color-disabled` | Wait; do not click again |

When a component library exists, add `@storybook/html` stories that mount these
five objects against the same tokens. Until then, `tests/test_saas_ui_contract.py`
is the executable storybook: it runs the generated script and requires the
click contract.
