import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import win32api
import win32con
import win32event
import win32gui
import win32process

from tests.runtime.probe_io import read_line

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", params=["source", "frozen"])
def probe_argv(request: pytest.FixtureRequest) -> list[str]:
    if request.param == "source":
        return [
            sys._base_executable,
            "-u",
            "-X",
            "utf8",
            "-m",
            "probes.entrypoint",
            "--role=supervisor",
        ]
    source = ROOT / "backend/dist/avi_probe"
    assert (source / "avi_probe.exe").is_file(), "Build avi_probe.spec before packaging tests"
    target = ROOT / ".cache/中文 空格路径/backend probe"
    shutil.copytree(source, target, dirs_exist_ok=True)
    return [str(target / "avi_probe.exe"), "--role=supervisor"]


@pytest.fixture
def supervisor(probe_argv: list[str]) -> Iterator[subprocess.Popen[bytes]]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA"}
    }
    # The frozen run cannot resolve any installed Python via PATH.
    environment["PATH"] = environment.get("SystemRoot", r"C:\Windows") + r"\System32"
    if probe_argv[0] == sys._base_executable:
        environment["__PYVENV_LAUNCHER__"] = sys.executable
    owner = subprocess.Popen(
        probe_argv,
        cwd=ROOT / "backend",
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        yield owner
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        for stream in (owner.stdin, owner.stdout, owner.stderr):
            if stream:
                stream.close()


def ready(owner: subprocess.Popen[bytes]) -> int:
    assert owner.stdout and owner.stderr
    data = read_line(owner.stdout)
    assert data, read_line(owner.stderr)
    frame = json.loads(data)
    assert frame["supervisorPid"] == owner.pid
    assert frame["streams"] is True
    assert read_line(owner.stderr) == b"T01-A probe started\n"
    pids = {owner.pid, frame["apiPid"]}
    visible: list[int] = []

    def inspect_window(hwnd: int, _: object) -> bool:
        if (
            win32gui.IsWindowVisible(hwnd)
            and win32process.GetWindowThreadProcessId(hwnd)[1] in pids
        ):
            visible.append(hwnd)
        return True

    win32gui.EnumWindows(inspect_window, None)
    assert not visible, "Probe processes must not display console windows"
    return int(frame["apiPid"])


@pytest.mark.parametrize("stop", ["command", "eof", "api_crash", "supervisor_crash"])
def test_probe_cleanup(supervisor: subprocess.Popen[bytes], stop: str) -> None:
    api_pid = ready(supervisor)
    api_handle = win32api.OpenProcess(
        win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, api_pid
    )
    try:
        assert supervisor.stdin and supervisor.stdout
        if stop == "supervisor_crash":
            supervisor.kill()
        else:
            if stop == "api_crash":
                win32process.TerminateProcess(api_handle, 9)
            elif stop == "eof":
                supervisor.stdin.close()
            else:
                supervisor.stdin.write(b"STOP\n")
                supervisor.stdin.flush()
            result = json.loads(read_line(supervisor.stdout, timeout=8))
            assert result["stopped"] is True
            assert result["activeJobProcesses"] == 0
            assert supervisor.wait(timeout=3) == 0
        supervisor.wait(timeout=3)
        assert win32event.WaitForSingleObject(api_handle, 2000) == 0
    finally:
        api_handle.Close()
