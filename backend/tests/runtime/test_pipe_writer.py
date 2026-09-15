import msvcrt
import os
import threading

import pytest
import win32pipe
from app.runtime.control_protocol import FRAME_LIMIT, ProtocolError
from app.runtime.pipe_writer import PipeWriter


def test_partial_writes_preserve_frame_order() -> None:
    output = bytearray()

    def partial(data: bytes) -> int:
        output.extend(data[:3])
        return min(3, len(data))

    writer = PipeWriter(partial)
    try:
        writer.enqueue(b"first\n")
        writer.enqueue(b"second\n")
        writer.drain()
        assert output == b"first\nsecond\n"
    finally:
        writer.close()


def test_active_write_counts_toward_queue_limit() -> None:
    release = threading.Event()
    entered = threading.Event()

    def blocked(data: bytes) -> int:
        entered.set()
        assert release.wait(3)
        return len(data)

    writer = PipeWriter(blocked)
    try:
        frame = b"x" * (FRAME_LIMIT - 1) + b"\n"
        writer.enqueue(frame)
        assert entered.wait(1)
        for _ in range(3):
            writer.enqueue(frame)
        with pytest.raises(ProtocolError):
            writer.enqueue(b"extra\n")
        with pytest.raises(ProtocolError):
            writer.check()
    finally:
        release.set()
        writer.close()


def test_stalled_writer_fails_after_two_seconds_without_echo() -> None:
    release = threading.Event()
    entered = threading.Event()
    now = [0.0]

    def blocked(data: bytes) -> int:
        entered.set()
        assert release.wait(3)
        return len(data)

    writer = PipeWriter(blocked, clock=lambda: now[0])
    try:
        writer.enqueue(b"SECRET_SENTINEL\n")
        assert entered.wait(1)
        now[0] = 1.999
        writer.check()
        now[0] = 2
        with pytest.raises(ProtocolError, match="^控制协议无效。$"):
            writer.check()
    finally:
        release.set()
        writer.close()


def test_write_exception_is_sanitized() -> None:
    def fail(_: bytes) -> int:
        raise OSError("SECRET_SENTINEL")

    writer = PipeWriter(fail)
    try:
        writer.enqueue(b"frame\n")
        with pytest.raises(ProtocolError, match="^控制协议无效。$"):
            writer.drain()
    finally:
        writer.close()


def test_real_windows_pipe_with_stalled_reader_is_bounded() -> None:
    reader, output = win32pipe.CreatePipe(None, 4096)
    fd = msvcrt.open_osfhandle(output.Detach(), os.O_BINARY | os.O_WRONLY)
    entered = threading.Event()
    now = [0.0]

    def write(data: bytes) -> int:
        entered.set()
        return os.write(fd, data)

    writer = PipeWriter(write, clock=lambda: now[0])
    try:
        writer.enqueue(b"x" * (FRAME_LIMIT - 1) + b"\n")
        assert entered.wait(1)
        now[0] = 2
        with pytest.raises(ProtocolError):
            writer.check()
    finally:
        reader.Close()
        writer.close()
        writer._thread.join(timeout=2)
        os.close(fd)
    assert not writer._thread.is_alive()
