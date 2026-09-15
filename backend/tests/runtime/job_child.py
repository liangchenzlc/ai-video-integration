"""Real child process fixture; only the job owner decides its lifetime."""

import json
import subprocess
import sys
import time

if "--grandchild" in sys.argv:
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", "import time; time.sleep(120)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    print(json.dumps({"grandchild": child.pid}), flush=True)
else:
    print("ready", flush=True)

if "--wait-eof" in sys.argv:
    sys.stdin.buffer.read()
else:
    time.sleep(120)
