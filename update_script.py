import re

with open('saas_web.py', 'r') as f:
    content = f.read()

content = content.replace("""                if (!file) {
                    preview.innerText = '';
                    return;
                }""", """                if (!file) {
                    preview.innerText = 'This field is required.';
                    preview.style.color = '#dc3545';
                    input.setCustomValidity('This field is required.');
                    input.setAttribute('aria-invalid', 'true');
                    return;
                }""")

content = content.replace("""                if (this.value === '') {
                    preview.innerText = '';
                    this.setCustomValidity('');
                    this.removeAttribute('aria-invalid');
                    return;
                }""", """                if (this.value === '') {
                    preview.innerText = 'This field is required.';
                    preview.style.color = '#dc3545';
                    this.setCustomValidity('This field is required.');
                    this.setAttribute('aria-invalid', 'true');
                    return;
                }""")

content = content.replace("""                const files = input.files;
                if (!files || files.length === 0) {
                    preview.innerText = '';
                    return;
                }""", """                const files = input.files;
                if (!files || files.length === 0) {
                    preview.innerText = 'This field is required.';
                    preview.style.color = '#dc3545';
                    input.setCustomValidity('This field is required.');
                    input.setAttribute('aria-invalid', 'true');
                    return;
                }""")

with open('saas_web.py', 'w') as f:
    f.write(content)
