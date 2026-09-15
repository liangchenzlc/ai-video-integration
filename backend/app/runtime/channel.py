"""Small role-independent control helpers; all output passes through the bounded writer."""

import os
import time

from app.runtime.control_protocol import (
    ControlErrorCode,
    Direction,
    FrameEncoder,
    InitFrame,
    ProtocolError,
)
from app.runtime.inbox import ControlInbox
from app.runtime.pipe_writer import PipeWriter

ERROR_MESSAGES: dict[ControlErrorCode, str] = {
    "INIT_TIMEOUT": "本地服务初始化超时。",
    "PROTOCOL_INVALID": "本地连接协议无效。",
    "JOB_SETUP_FAILED": "无法建立安全的进程管理。",
    "API_SPAWN_FAILED": "本地服务进程启动失败。",
    "API_EXITED": "本地服务进程已退出。",
    "START_TIMEOUT": "本地服务启动超时。",
    "STOP_TIMEOUT": "无法确认本地服务已完全停止。",
    "BIND_FAILED": "无法建立本地服务连接。",
    "BACKEND_ALREADY_RUNNING": "本地服务已在其他实例中运行。",
    "INTERNAL_ERROR": "本地服务遇到错误。",
}


def read_init(inbox: ControlInbox, started: float) -> InitFrame:
    while time.monotonic() < started + 5:
        event = inbox.poll()
        if isinstance(event, InitFrame):
            return event
        if event is not None:
            raise ProtocolError()
        time.sleep(0.01)
    raise TimeoutError("Initialization deadline exceeded")


class ControlOutput:
    def __init__(self, fd: int, direction: Direction, init: InitFrame) -> None:
        self.encoder = FrameEncoder(direction, init.runtime_id, init.generation)
        self.writer = PipeWriter(lambda data: os.write(fd, data))

    def emit(self, message_type: str, payload: dict[str, object]) -> None:
        self.writer.enqueue(self.encoder.encode(message_type, payload))

    def error(self, code: ControlErrorCode) -> None:
        self.emit("error", {"code": code, "message": ERROR_MESSAGES[code]})
