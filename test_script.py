import subprocess
print(subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests"], capture_output=True).stderr.decode('utf-8'))
