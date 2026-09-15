"""Bounded reads for real Windows pipe probes, without blocked reader threads."""

import msvcrt
import os
import time
from typing import BinaryIO

import pywintypes
import win32pipe


def read_line(stream: BinaryIO, timeout: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout
    fd = stream.fileno()
    handle = msvcrt.get_osfhandle(fd)
    result = bytearray()
    while time.monotonic() < deadline:
        try:
            available = win32pipe.PeekNamedPipe(handle, 0)[1]
        except pywintypes.error as exc:
            if exc.winerror == 109:
                return bytes(result)
            raise
        if available:
            result.extend(os.read(fd, 1))
            if result.endswith(b"\n"):
                return bytes(result)
            if len(result) >= 16384:
                raise ValueError("Probe output exceeds limit")
        else:
            time.sleep(0.01)
    raise TimeoutError("Probe did not respond within deadline")
