import json
import subprocess
import sys
from pathlib import Path

import pytest
import pywintypes
import win32api
import win32con
import win32event
import win32job
import win32pipe
import win32process
from app.runtime.windows_job import WindowsJob

from tests.runtime.probe_io import read_line

FIXTURE = Path(__file__).with_name("job_child.py")


def test_handle_allowlist_excludes_unrelated_inheritable_pipe() -> None:
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.bInheritHandle = True
    read_handle, write_handle = win32pipe.CreatePipe(attributes, 0)
    win32api.SetHandleInformation(read_handle, win32con.HANDLE_FLAG_INHERIT, 0)
    try:
        with WindowsJob() as job:
            child = job.spawn_suspended_in_job(
                [sys.executable, "-u", str(FIXTURE)], cwd=str(Path.cwd())
            )
            try:
                assert read_line(child.stdout).strip() == b"ready"
                write_handle.Close()
                # An inherited writer would keep this pipe open while child lives.
                with pytest.raises(pywintypes.error) as error:
                    win32pipe.PeekNamedPipe(read_handle, 0)
                assert error.value.winerror == 109
            finally:
                job.terminate_job()
                child.wait()
                child.close()
    finally:
        write_handle.Close()
        read_handle.Close()


def test_job_owns_child_and_descendant_but_not_unrelated_process() -> None:
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    child = None
    descendant_handle = None
    try:
        with WindowsJob() as job:
            child = job.spawn_suspended_in_job(
                [sys.executable, "-u", str(FIXTURE), "--grandchild"], cwd=str(Path.cwd())
            )
            descendant_pid = json.loads(read_line(child.stdout))["grandchild"]
            descendant_handle = win32api.OpenProcess(
                win32con.SYNCHRONIZE | 0x1000, False, descendant_pid
            )
            assert job.contains(child)
            assert win32job.IsProcessInJob(descendant_handle, job._handle)
            # Windows may create additional hidden conhost processes in the Job.
            assert job.active_processes() >= 2
            assert not win32job.IsProcessInJob(win32api.GetCurrentProcess(), job._handle)
            job.terminate_job()
            assert job.wait_empty()
            child.wait()
            assert win32event.WaitForSingleObject(descendant_handle, 2000) == 0
            assert unrelated.poll() is None
    finally:
        if child:
            child.close()
        if descendant_handle:
            descendant_handle.Close()
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_closing_last_job_handle_kills_member() -> None:
    job = WindowsJob()
    child = job.spawn_suspended_in_job([sys.executable, "-u", str(FIXTURE)], cwd=str(Path.cwd()))
    try:
        assert read_line(child.stdout).strip() == b"ready"
        job.close()
        child.wait()
        job.close()  # Idempotent teardown.
    finally:
        job.close()
        child.close()


def test_parent_pipe_eof_is_not_held_open_by_inherited_parent_handles() -> None:
    with WindowsJob() as job:
        child = job.spawn_suspended_in_job(
            [sys.executable, "-u", str(FIXTURE), "--wait-eof"], cwd=str(Path.cwd())
        )
        try:
            assert read_line(child.stdout).strip() == b"ready"
            child.stdin.close()
            assert child.wait() == 0
            assert job.wait_empty()
        finally:
            child.close()


def test_invalid_executable_leaves_empty_job() -> None:
    with WindowsJob() as job:
        with pytest.raises(OSError):
            job.spawn_suspended_in_job(["Z:\\missing\\process.exe"], cwd=str(Path.cwd()))
        assert job.active_processes() == 0


def test_assignment_failure_terminates_still_suspended_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_handles = []

    def fail(_job: object, process: object) -> None:
        pid = win32process.GetProcessId(process)
        observed_handles.append(win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid))
        raise RuntimeError("injected assignment failure")

    try:
        with WindowsJob() as job:
            monkeypatch.setattr(win32job, "AssignProcessToJobObject", fail)
            with pytest.raises(RuntimeError, match="assignment failure"):
                job.spawn_suspended_in_job(
                    [sys.executable, "-u", str(FIXTURE)], cwd=str(Path.cwd())
                )
            assert job.active_processes() == 0
            assert len(observed_handles) == 1
            assert win32event.WaitForSingleObject(observed_handles[0], 2000) == 0
    finally:
        for handle in observed_handles:
            handle.Close()


def test_owner_crash_reaps_tree_without_explicit_terminate() -> None:
    owner = subprocess.Popen(
        [sys.executable, "-u", "-m", "tests.runtime.job_owner"],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    handles = []
    try:
        assert owner.stdout is not None
        data = read_line(owner.stdout)
        assert data, "Owner exited without reporting its tree"
        pids = json.loads(data)
        handles = [win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid) for pid in pids.values()]
        owner.kill()
        owner.wait(timeout=5)
        assert all(win32event.WaitForSingleObject(handle, 3000) == 0 for handle in handles)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        for handle in handles:
            handle.Close()
        if owner.stdout:
            owner.stdout.close()
        if owner.stderr:
            owner.stderr.close()
