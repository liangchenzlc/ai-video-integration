import json
import sys
from pathlib import Path

import win32api
import win32con
import win32event
from app.runtime.process_tree import finish_tree
from app.runtime.windows_job import WindowsJob

from tests.runtime.probe_io import read_line

FIXTURE = Path(__file__).with_name("job_child.py")


def test_graceful_eof_does_not_require_force() -> None:
    with WindowsJob() as job:
        child = job.spawn_suspended_in_job(
            [sys.executable, "-u", str(FIXTURE), "--wait-eof"], cwd=str(Path.cwd())
        )
        try:
            assert read_line(child.stdout).strip() == b"ready"
            child.stdin.close()
            result = finish_tree(job, child)
            assert not result.forced
            assert result.active_processes == 0
        finally:
            child.close()


def test_stuck_descendant_is_reaped_after_root_exits() -> None:
    with WindowsJob() as job:
        child = job.spawn_suspended_in_job(
            [sys.executable, "-u", str(FIXTURE), "--grandchild", "--wait-eof"],
            cwd=str(Path.cwd()),
        )
        handle = None
        try:
            pid = json.loads(read_line(child.stdout))["grandchild"]
            handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
            child.stdin.close()
            child.wait()
            result = finish_tree(job, child, grace_ms=100)
            assert result.forced
            assert result.active_processes == 0
            assert win32event.WaitForSingleObject(handle, 2000) == 0
        finally:
            if handle:
                handle.Close()
            child.close()
