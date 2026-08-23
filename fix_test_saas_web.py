import re

with open('tests/test_saas_web.py', 'r') as f:
    content = f.read()

content = content.replace("""    def test_get_ui_includes_binary_file_size_validation(self):""", """    def test_get_ui_includes_binary_file_size_validation(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("preview.innerText = 'This field is required.';", html)
        self.assertIn("preview.style.color = '#dc3545';", html)
        self.assertIn("input.setCustomValidity('This field is required.');", html)
        self.assertIn("input.setAttribute('aria-invalid', 'true');", html)""")

with open('tests/test_saas_web.py', 'w') as f:
    f.write(content)
