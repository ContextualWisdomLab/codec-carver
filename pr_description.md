💡 What
Added a CSS spinning loader animation to the form submission button and updated the javascript inline script to replace the button's content with an ARIA-hidden spinner alongside "Processing...".

🎯 Why
When users submit the form (which processes large media files), the action may take significant time. Adding an immediate, visual spinning loading state reassures the user that their submission is actively being processed, preventing confusion and double submissions.

📸 Before/After
Before: The button text simply changed to "Processing...".
After: The button text changes to "Processing..." accompanied by a smoothly animating CSS spinner.

♿ Accessibility
The spinner span includes `aria-hidden="true"` so that screen readers do not attempt to announce the empty decorative element. Screen readers already receive the `aria-busy="true"` attribute (added previously) and the text update, so this visual addition improves the experience for sighted users without creating noise for non-visual users.
