"""T01-A packaging fixture only; not the application or its control protocol.

The same frozen executable serves both probe roles. This deliberately has no
HTTP, credentials, business data or renderer commands. It exercises the real
process adapter and bounded cleanup before the product protocol is connected.
"""

import argparse
import json
import msvcrt
import os
import sys
import time
from pathlib import Path
from typing import BinaryIO

import pywintypes
import win32pipe
from app.runtime.process_tree import finish_tree
from app.runtime.python_launch import python_launch
from app.runtime.windows_job import WindowsJob


def read_available(stream: BinaryIO) -> bytes | None:
    """Return None while open/empty, b'' for EOF; limit probe input to 32 bytes."""
    fd = stream.fileno()
    try:
        available = win32pipe.PeekNamedPipe(msvcrt.get_osfhandle(fd), 0)[1]
    except pywintypes.error as exc:
        if exc.winerror == 109:
            return b""
        raise
    return os.read(fd, min(available, 32)) if available else None


def emit(value: dict[str, object]) -> None:
    sys.stdout.buffer.write(json.dumps(value).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def run_api() -> int:
    emit({"apiPid": os.getpid(), "streams": True})
    while True:
        # Any input/EOF stops this fixture. Actual protocol arrives in T01-B.
        if read_available(sys.stdin.buffer) is not None:
            return 0
        time.sleep(0.01)


def run_supervisor() -> int:
    frozen = getattr(sys, "frozen", False)
    launch = python_launch("probes.entrypoint", ["--role=api"])
    cwd = str(Path(sys.executable).parent) if frozen else str(Path(__file__).resolve().parents[1])
    with WindowsJob() as job:
        child = job.spawn_suspended_in_job(launch.argv, cwd=cwd, env=launch.environment)
        try:
            deadline = time.monotonic() + 5
            response = bytearray()
            while b"\n" not in response:
                data = read_available(child.stdout)
                if data == b"" or time.monotonic() >= deadline:
                    raise TimeoutError("Probe API did not start")
                if data:
                    response.extend(data)
                    if len(response) > 256:
                        raise ValueError("Probe API output too large")
                time.sleep(0.01)
            api = json.loads(response)
            if api != {"apiPid": child.pid, "streams": True}:
                raise ValueError("Probe child identity mismatch")
            emit({"supervisorPid": os.getpid(), **api})
            while child.poll() is None:
                if read_available(sys.stdin.buffer) is not None:
                    child.stdin.close()
                    break
                time.sleep(0.01)
            result = finish_tree(job, child)
            emit(
                {
                    "stopped": True,
                    "forced": result.forced,
                    "activeJobProcesses": result.active_processes,
                }
            )
            return 0
        finally:
            job.close()
            child.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal T01-A packaging probe")
    parser.add_argument("--role", choices=("supervisor", "api"), required=True)
    args = parser.parse_args()
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is None:
            raise RuntimeError("Probe requires all three standard streams")
        msvcrt.setmode(stream.fileno(), os.O_BINARY)
    # Verify stderr separately from the machine-readable stdout channel.
    sys.stderr.buffer.write(b"T01-A probe started\n")
    sys.stderr.buffer.flush()
    return run_supervisor() if args.role == "supervisor" else run_api()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
