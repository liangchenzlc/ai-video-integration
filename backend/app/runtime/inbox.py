"""Dedicated pipe reader with a bounded event queue; never logs peer data."""

import os
import queue
import threading
from typing import Literal

from app.runtime.control_protocol import Direction, Frame, FrameDecoder

type InputEvent = Frame | Literal["eof", "invalid"]


class ControlInbox:
    def __init__(
        self,
        fd: int,
        direction: Direction,
        runtime_id: str | None = None,
        generation: int | None = None,
    ) -> None:
        self._decoder = FrameDecoder(direction, runtime_id, generation)
        self._events: queue.Queue[Frame] = queue.Queue(maxsize=32)
        self._failed = threading.Event()
        self._eof = threading.Event()
        self._thread = threading.Thread(
            target=self._read, args=(fd,), daemon=True, name="control-pipe-reader"
        )
        self._thread.start()

    def _read(self, fd: int) -> None:
        try:
            while raw := os.read(fd, 4096):
                for frame in self._decoder.feed(raw):
                    self._events.put_nowait(frame)
            self._decoder.eof()
            self._eof.set()
        except Exception:
            self._failed.set()

    def poll(self) -> InputEvent | None:
        if self._failed.is_set():
            return "invalid"
        try:
            return self._events.get_nowait()
        except queue.Empty:
            return "eof" if self._eof.is_set() else None

    @property
    def disconnected(self) -> bool:
        return self._failed.is_set() or self._eof.is_set()

    @property
    def invalid(self) -> bool:
        return self._failed.is_set()


class DiagnosticDrain:
    def __init__(self, fd: int) -> None:
        self.overflowed = threading.Event()
        threading.Thread(
            target=self._read, args=(fd,), daemon=True, name="diagnostic-drain"
        ).start()

    def _read(self, fd: int) -> None:
        size = 0
        try:
            while raw := os.read(fd, 4096):
                size += len(raw)
                if size > 65536:
                    self.overflowed.set()
                    return
        except OSError:
            pass
