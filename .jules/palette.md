
## 2024-06-05 - Implicit defaults hide CLI state
**Learning:** When python's argparse defaults are used without `ArgumentDefaultsHelpFormatter`, users cannot see what the tool will do out of the box, breaking mental model and forcing them to read the code or guess. Explicit labels in web forms are necessary for screen readers.
**Action:** Always configure argparse to show defaults. Ensure web form inputs have explicit `<label>` tags with matching `id` and `for` attributes.
