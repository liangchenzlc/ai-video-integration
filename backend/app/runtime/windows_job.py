"""Own a Windows Job and start hidden children suspended until assigned to it.

The supervisor alone owns the non-inheritable Job handle. Closing that handle,
including on supervisor death, lets Windows clean up the entire owned tree.
"""

from __future__ import annotations

import _winapi
import msvcrt
import os
import subprocess
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any, BinaryIO, cast

import pywintypes
import win32api
import win32con
import win32event
import win32job
import win32pipe
import win32process

_CREATE_LOCK = threading.Lock()


def _close(handle: Any) -> None:
    if handle is not None:
        handle.Close()


def _stream(handle: Any, mode: str) -> BinaryIO:
    flags = os.O_BINARY | (os.O_RDONLY if mode == "rb" else os.O_WRONLY)
    raw_handle = handle.Detach()
    try:
        fd = msvcrt.open_osfhandle(raw_handle, flags)
    except BaseException:
        win32api.CloseHandle(raw_handle)
        raise
    try:
        return cast(BinaryIO, os.fdopen(fd, mode, buffering=0))
    except BaseException:
        os.close(fd)
        raise


@dataclass
class ManagedProcess:
    pid: int
    stdin: BinaryIO = field(repr=False)
    stdout: BinaryIO = field(repr=False)
    stderr: BinaryIO = field(repr=False)
    _handle: Any = field(repr=False)
    _closed: bool = False

    def poll(self) -> int | None:
        if win32event.WaitForSingleObject(self._handle, 0) == win32event.WAIT_TIMEOUT:
            return None
        return int(win32process.GetExitCodeProcess(self._handle))

    def wait(self, timeout_ms: int = 5000) -> int:
        if win32event.WaitForSingleObject(self._handle, timeout_ms) == win32event.WAIT_TIMEOUT:
            raise TimeoutError("Owned process did not exit within deadline")
        return int(win32process.GetExitCodeProcess(self._handle))

    def terminate(self, exit_code: int = 1) -> None:
        if self.poll() is None:
            win32process.TerminateProcess(self._handle, exit_code)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            with ExitStack() as cleanup:
                cleanup.callback(_close, self._handle)
                for stream in (self.stdin, self.stdout, self.stderr):
                    cleanup.callback(stream.close)


class WindowsJob:
    def __init__(self) -> None:
        self._handle = win32job.CreateJobObject(None, "")
        try:
            win32api.SetHandleInformation(self._handle, win32con.HANDLE_FLAG_INHERIT, 0)
            info = win32job.QueryInformationJobObject(
                self._handle, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                self._handle, win32job.JobObjectExtendedLimitInformation, info
            )
        except BaseException:
            _close(self._handle)
            raise
        self._closed = False

    def spawn_suspended_in_job(
        self, argv: list[str], *, cwd: str, env: dict[str, str] | None = None
    ) -> ManagedProcess:
        if self._closed:
            raise RuntimeError("Job is already closed")
        if not argv or not os.path.isabs(argv[0]):
            raise ValueError("A fixed absolute executable is required")
        handles: list[Any] = []
        process_handle = thread_handle = None
        streams: list[BinaryIO] = []
        # CPython's native CreateProcess wrapper supports STARTUPINFOEX and an
        # explicit handle allowlist; pywin32's STARTUPINFO does not. Keep the
        # temporary inheritable handles serialized, even across concurrent jobs.
        with _CREATE_LOCK:
            try:
                sa = pywintypes.SECURITY_ATTRIBUTES()
                sa.bInheritHandle = True
                child_input, parent_input = win32pipe.CreatePipe(sa, 0)
                handles.extend([child_input, parent_input])
                parent_output, child_output = win32pipe.CreatePipe(sa, 0)
                handles.extend([parent_output, child_output])
                parent_error, child_error = win32pipe.CreatePipe(sa, 0)
                handles.extend([parent_error, child_error])
                for parent in (parent_input, parent_output, parent_error):
                    win32api.SetHandleInformation(parent, win32con.HANDLE_FLAG_INHERIT, 0)
                startup = subprocess.STARTUPINFO()
                startup.dwFlags = win32con.STARTF_USESTDHANDLES
                startup.hStdInput = int(child_input)
                startup.hStdOutput = int(child_output)
                startup.hStdError = int(child_error)
                startup.lpAttributeList = {
                    "handle_list": [int(child_input), int(child_output), int(child_error)]
                }
                process_raw, thread_raw, pid, _ = _winapi.CreateProcess(
                    argv[0],
                    subprocess.list2cmdline(argv),
                    None,
                    None,
                    True,
                    win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW,
                    os.environ.copy() if env is None else env,
                    cwd,
                    startup,
                )
                process_handle = pywintypes.HANDLE(process_raw)
                thread_handle = pywintypes.HANDLE(thread_raw)
                win32api.SetHandleInformation(process_handle, win32con.HANDLE_FLAG_INHERIT, 0)
                win32job.AssignProcessToJobObject(self._handle, process_handle)
                # Convert owned parent handles before running any child code.
                for handle, mode in (
                    (parent_input, "wb"),
                    (parent_output, "rb"),
                    (parent_error, "rb"),
                ):
                    handles.remove(handle)
                    streams.append(_stream(handle, mode))
                if win32process.ResumeThread(thread_handle) != 1:
                    raise RuntimeError("Unexpected suspended thread state")
                return ManagedProcess(pid, streams[0], streams[1], streams[2], process_handle)
            except BaseException:
                with ExitStack() as cleanup:
                    if process_handle is not None:
                        cleanup.callback(_close, process_handle)
                    for stream in streams:
                        cleanup.callback(stream.close)
                    if process_handle is not None:
                        win32process.TerminateProcess(process_handle, 1)
                        win32event.WaitForSingleObject(process_handle, 2000)
                raise
            finally:
                with ExitStack() as cleanup:
                    cleanup.callback(_close, thread_handle)
                    for handle in handles:
                        cleanup.callback(_close, handle)

    def active_processes(self) -> int:
        if self._closed:
            raise RuntimeError("Job is already closed")
        info = win32job.QueryInformationJobObject(
            self._handle, win32job.JobObjectBasicAccountingInformation
        )
        return int(info["ActiveProcesses"])

    def contains(self, process: ManagedProcess) -> bool:
        return bool(win32job.IsProcessInJob(process._handle, self._handle))

    def terminate_job(self, exit_code: int = 1) -> None:
        if not self._closed:
            win32job.TerminateJobObject(self._handle, exit_code)

    def wait_empty(self, timeout_ms: int = 2000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while self.active_processes():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _close(self._handle)

    def __enter__(self) -> WindowsJob:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
