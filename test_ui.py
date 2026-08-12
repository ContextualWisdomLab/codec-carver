import re

with open("saas_web.py") as f:
    html = f.read()

assert "dropZone.addEventListener('click'" not in html
print("Looks good.")
