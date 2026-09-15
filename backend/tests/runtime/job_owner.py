"""Fixture used to verify that OS teardown closes the only Job handle."""

import json
import sys
import time
from pathlib import Path

from app.runtime.windows_job import WindowsJob

from tests.runtime.probe_io import read_line

job = WindowsJob()
child = job.spawn_suspended_in_job(
    [sys.executable, "-u", str(Path(__file__).with_name("job_child.py")), "--grandchild"],
    cwd=str(Path.cwd()),
)
descendant = json.loads(read_line(child.stdout))
print(json.dumps({"pid": child.pid, **descendant}), flush=True)
time.sleep(120)
