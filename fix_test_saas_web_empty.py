import re

with open('tests/test_saas_web.py', 'r') as f:
    content = f.read()

content = content.replace("""        self.assertIn("preview.innerText = 'Must be greater than 0.';", html)""", """        self.assertIn("preview.innerText = 'This field is required.';", html)\n        self.assertIn("preview.innerText = 'Must be greater than 0.';", html)""")

with open('tests/test_saas_web.py', 'w') as f:
    f.write(content)
