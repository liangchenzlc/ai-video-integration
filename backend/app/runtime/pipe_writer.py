"""One bounded daemon writer. The owner polls check() and owns pipe teardown."""

import threading
import time
from collections import deque
from collections.abc import Callable

from app.runtime.control_protocol import (
    FRAME_LIMIT,
    WRITE_LIMIT,
    WRITE_TIMEOUT_SECONDS,
    ProtocolError,
)


class PipeWriter:
    def __init__(
        self, write: Callable[[bytes], int], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._write = write
        self._clock = clock
        self._condition = threading.Condition()
        self._queue: deque[bytes] = deque()
        self._pending_bytes = 0
        self._last_progress = clock()
        self._closed = self._failed = False
        self._thread = threading.Thread(target=self._run, name="control-pipe-writer", daemon=True)
        self._thread.start()

    def _fail(self) -> None:
        self._failed = self._closed = True
        self._queue.clear()
        self._pending_bytes = 0
        self._condition.notify_all()

    def enqueue(self, frame: bytes) -> None:
        with self._condition:
            if self._closed:
                raise ProtocolError()
            if (
                not frame
                or not frame.endswith(b"\n")
                or len(frame) > FRAME_LIMIT
                or self._pending_bytes + len(frame) > WRITE_LIMIT
            ):
                self._fail()
                raise ProtocolError()
            if not self._pending_bytes:
                self._last_progress = self._clock()
            self._queue.append(bytes(frame))
            self._pending_bytes += len(frame)
            self._condition.notify_all()

    def check(self) -> None:
        with self._condition:
            if self._pending_bytes and self._clock() - self._last_progress >= WRITE_TIMEOUT_SECONDS:
                self._fail()
            if self._failed:
                raise ProtocolError()

    def drain(self, timeout: float = WRITE_TIMEOUT_SECONDS) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._pending_bytes and not self._failed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._fail()
                    break
                self._condition.wait(min(remaining, 0.05))
                self.check()
            if self._failed:
                raise ProtocolError()

    def close(self) -> None:
        # Never join a thread blocked in a synchronous OS write. Runtime owner
        # closes the pipe/process after failure; use os.write, not buffered stdio.
        with self._condition:
            self._failed = self._failed or bool(self._pending_bytes)
            self._closed = True
            self._queue.clear()
            self._pending_bytes = 0
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or bool(self._queue))
                if self._closed:
                    return
                frame = self._queue.popleft()
            offset = 0
            try:
                while offset < len(frame):
                    written = self._write(frame[offset:])
                    if not 0 < written <= len(frame) - offset:
                        raise ProtocolError()
                    with self._condition:
                        if self._closed:
                            return
                        offset += written
                        self._pending_bytes -= written
                        self._last_progress = self._clock()
                        self._condition.notify_all()
            except Exception:
                with self._condition:
                    if not self._closed:
                        self._fail()
                return
