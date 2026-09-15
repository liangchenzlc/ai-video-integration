import secrets
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import win32api
import win32con
import win32event
import win32process
from app.runtime.control_protocol import (
    BootedFrame,
    ErrorFrame,
    Frame,
    FrameDecoder,
    FrameEncoder,
    ReadyFrame,
    StopAckFrame,
    StoppedFrame,
)
from app.runtime.python_launch import python_launch
from app.runtime.windows_job import ManagedProcess, WindowsJob

from tests.runtime.probe_io import read_line

ROOT = Path(__file__).resolve().parents[3]


class LiveRuntime:
    def __init__(self, process: ManagedProcess) -> None:
        self.process = process
        self.identity = str(uuid4())
        self.token = secrets.token_urlsafe(32)
        self.encoder = FrameEncoder("mainToSupervisor", self.identity, 1)
        self.decoder = FrameDecoder("supervisorToMain", self.identity, 1)
        self.ready_frame: ReadyFrame | None = None
        self.api_handle = None

    def initialize(self) -> None:
        self.process.stdin.write(
            self.encoder.encode(
                "init",
                {
                    "tokenB64Url": self.token,
                    "appDataDir": str(ROOT / ".cache/runtime-app"),
                    "mode": "production",
                    "expectedApiVersion": 1,
                    "expectedBackendVersion": "0.1.0",
                },
            )
        )

    def read(self, timeout: float = 8) -> Frame:
        raw = read_line(self.process.stdout, timeout)
        assert raw, "Supervisor exited before its expected frame"
        frames = self.decoder.feed(raw)
        assert len(frames) == 1
        return frames[0]

    def wait_ready(self) -> None:
        booted = self.read()
        assert isinstance(booted, BootedFrame), type(booted).__name__
        assert booted.payload.supervisor_pid == self.process.pid
        self.api_handle = win32api.OpenProcess(
            win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, booted.payload.api_pid
        )
        frame = self.read()
        assert isinstance(frame, ReadyFrame), (
            frame.payload.code if isinstance(frame, ErrorFrame) else type(frame).__name__
        )
        assert frame.payload.api_pid == booted.payload.api_pid
        self.ready_frame = frame

    def health(self, headers: dict[str, str] | None = None) -> httpx.Response:
        assert self.ready_frame is not None
        with httpx.Client(trust_env=False, timeout=1.5) as http:
            return http.get(
                f"http://127.0.0.1:{self.ready_frame.payload.port}/api/v1/health",
                headers=headers
                if headers is not None
                else {"Authorization": "Bearer " + self.token},
            )

    def request_stop(self) -> None:
        self.process.stdin.write(self.encoder.encode("stop", {"reason": "user_restart"}))

    def finish_stop(self) -> None:
        ack = self.read()
        assert isinstance(ack, StopAckFrame) and ack.payload.for_seq == 2
        stopped = self.read()
        assert isinstance(stopped, StoppedFrame)
        assert stopped.payload.active_job_processes == 0
        assert self.process.wait(3000) == 0
        if self.api_handle:
            assert win32event.WaitForSingleObject(self.api_handle, 2000) == 0


@contextmanager
def runtime(
    initialize: bool = True, module: str = "app.entrypoint", executable: Path | None = None
) -> Iterator[LiveRuntime]:
    launch = python_launch(module, ["--role=supervisor"])
    argv = launch.argv
    cwd = ROOT / "backend"
    if executable:
        argv = [str(executable), "--role=supervisor"]
        cwd = executable.parent
        launch.environment.pop("__PYVENV_LAUNCHER__", None)
        launch.environment["PATH"] = r"C:\Windows\System32"
    with WindowsJob() as job:
        process = job.spawn_suspended_in_job(argv, cwd=str(cwd), env=launch.environment)
        instance = LiveRuntime(process)
        try:
            if initialize:
                instance.initialize()
            yield instance
        finally:
            job.terminate_job()
            assert job.wait_empty(2000)
            process.wait(2000)
            if instance.api_handle:
                instance.api_handle.Close()
            process.close()


def test_real_http_identity_security_and_graceful_shutdown() -> None:
    with runtime() as instance:
        instance.wait_ready()
        response = instance.health()
        assert response.status_code == 200
        assert response.json()["data"]["runtimeId"] == instance.identity
        assert response.json()["data"]["generation"] == 1
        assert response.json()["data"]["backendVersion"] == "0.1.0"
        assert instance.health({}).status_code == 401
        assert (
            instance.health(
                {"Authorization": "Bearer " + instance.token, "Origin": "null"}
            ).status_code
            == 403
        )
        instance.request_stop()
        instance.finish_stop()


@pytest.mark.parametrize(
    "fault", ["parent_eof", "supervisor_kill", "api_kill", "invalid_parent", "eof_during_stop"]
)
def test_real_process_fault_cleanup(fault: str) -> None:
    with runtime() as instance:
        instance.wait_ready()
        if fault == "parent_eof":
            instance.process.stdin.close()
        elif fault == "supervisor_kill":
            instance.process.terminate()
        elif fault == "api_kill":
            win32process.TerminateProcess(instance.api_handle, 9)
        elif fault == "invalid_parent":
            instance.process.stdin.write(b"INVALID_SECRET_SENTINEL\n")
        elif fault == "eof_during_stop":
            instance.request_stop()
            instance.process.stdin.close()
        instance.process.wait(3500)
        assert win32event.WaitForSingleObject(instance.api_handle, 2000) == 0
        if fault in ("api_kill", "invalid_parent"):
            frame = instance.read()
            assert isinstance(frame, ErrorFrame)
            assert frame.payload.code == (
                "API_EXITED" if fault == "api_kill" else "PROTOCOL_INVALID"
            )
            assert "SECRET_SENTINEL" not in frame.payload.message


def test_second_instance_cannot_steal_mutex_or_kill_first() -> None:
    with runtime() as first:
        first.wait_ready()
        with runtime() as second:
            assert isinstance(second.read(), BootedFrame)
            frame = second.read()
            assert isinstance(frame, ErrorFrame)
            assert frame.payload.code == "BACKEND_ALREADY_RUNNING"
            assert second.process.wait(3000) != 0
            assert first.health().status_code == 200
        first.request_stop()
        first.finish_stop()
    with runtime() as third:
        third.wait_ready()
        third.request_stop()
        third.finish_stop()


def test_missing_init_deadline_exits_without_identity_or_token_output() -> None:
    with runtime(initialize=False) as instance:
        started = time.monotonic()
        assert instance.process.wait(6500) != 0
        assert 4.5 <= time.monotonic() - started < 6.5
        assert instance.process.stdout.read() == b""
        assert instance.process.stderr.read() == b"INIT_TIMEOUT\n"


def test_stop_during_startup_never_requires_ready() -> None:
    with runtime() as instance:
        instance.request_stop()
        assert isinstance(instance.read(), BootedFrame)
        instance.finish_stop()


def test_stop_ack_is_not_exit_and_stubborn_tree_is_forced_after_grace() -> None:
    with runtime(module="tests.runtime.fault_supervisor") as instance:
        instance.wait_ready()
        started = time.monotonic()
        instance.request_stop()
        assert isinstance(instance.read(), StopAckFrame)
        with pytest.raises(TimeoutError):
            instance.process.wait(100)
        stopped = instance.read()
        assert isinstance(stopped, StoppedFrame)
        assert stopped.payload.forced is True
        assert stopped.payload.active_job_processes == 0
        assert 4.8 <= time.monotonic() - started < 7.5
        assert instance.process.wait(1000) == 0
        assert win32event.WaitForSingleObject(instance.api_handle, 2000) == 0


def test_parent_eof_interrupts_in_progress_grace_period() -> None:
    with runtime(module="tests.runtime.fault_supervisor") as instance:
        instance.wait_ready()
        instance.request_stop()
        assert isinstance(instance.read(), StopAckFrame)
        started = time.monotonic()
        instance.process.stdin.close()
        instance.process.wait(3000)
        assert time.monotonic() - started < 2.5
        assert win32event.WaitForSingleObject(instance.api_handle, 2000) == 0


def test_frozen_backend_in_chinese_space_path_without_python_path() -> None:
    source = ROOT / "backend/dist/avi_backend"
    assert (source / "avi_backend.exe").is_file(), (
        "Build avi_backend.spec before integration checks"
    )
    target = ROOT / ".cache/真实后端 中文 空格/avi_backend"
    shutil.copytree(source, target, dirs_exist_ok=True)
    with runtime(executable=target / "avi_backend.exe") as instance:
        instance.wait_ready()
        assert instance.health().status_code == 200
        instance.request_stop()
        instance.finish_stop()
