"""Bounded, strict control frames; no exception contains peer input."""

from __future__ import annotations

import base64
import json
import ntpath
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, TypeAdapter, field_validator

from app.api.v1.models import Generation, ProtocolVersion, StrictModel, Uuid, Version, json_integer

FRAME_LIMIT = 16 * 1024
WRITE_LIMIT = 64 * 1024
WRITE_TIMEOUT_SECONDS = 2.0

type Direction = Literal[
    "mainToSupervisor", "supervisorToApi", "apiToSupervisor", "supervisorToMain"
]
type StopReason = Literal["app_exit", "user_restart"]
type Pid = Annotated[int, Field(ge=1), BeforeValidator(json_integer)]
type Port = Annotated[int, Field(ge=1, le=65535), BeforeValidator(json_integer)]
type Zero = Annotated[Literal[0], BeforeValidator(json_integer)]
type ControlErrorCode = Literal[
    "INIT_TIMEOUT",
    "PROTOCOL_INVALID",
    "JOB_SETUP_FAILED",
    "API_SPAWN_FAILED",
    "API_EXITED",
    "START_TIMEOUT",
    "STOP_TIMEOUT",
    "BIND_FAILED",
    "BACKEND_ALREADY_RUNNING",
    "INTERNAL_ERROR",
]


class ProtocolError(Exception):
    def __init__(self) -> None:
        super().__init__("控制协议无效。")


class InitPayload(StrictModel):
    token_b64_url: str = Field(alias="tokenB64Url", pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    app_data_dir: str = Field(alias="appDataDir", min_length=1, max_length=1024)
    mode: Literal["development", "production"]
    expected_api_version: ProtocolVersion = Field(alias="expectedApiVersion")
    expected_backend_version: Version = Field(alias="expectedBackendVersion")

    @field_validator("token_b64_url")
    @classmethod
    def canonical_token(cls, value: str) -> str:
        raw = base64.urlsafe_b64decode(value + "=")
        if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != value:
            raise ValueError("Invalid canonical token")
        return value

    @field_validator("app_data_dir")
    @classmethod
    def absolute_directory(cls, value: str) -> str:
        drive = ntpath.splitdrive(value)[0]
        normalized_drive = drive.replace("/", "\\")
        valid_drive = (
            len(drive) == 2 and drive[0].isascii() and drive[0].isalpha() and drive[1] == ":"
        ) or (
            normalized_drive.startswith("\\\\")
            and len([part for part in normalized_drive.split("\\") if part]) >= 2
        )
        if not ntpath.isabs(value) or not valid_drive or any(ord(char) < 32 for char in value):
            raise ValueError("Expected an absolute Windows directory")
        return value


class BootedPayload(StrictModel):
    supervisor_pid: Pid = Field(alias="supervisorPid")
    api_pid: Pid = Field(alias="apiPid")


class ReadyPayload(StrictModel):
    host: Literal["127.0.0.1"]
    port: Port
    api_pid: Pid = Field(alias="apiPid")
    api_version: ProtocolVersion = Field(alias="apiVersion")
    backend_version: Version = Field(alias="backendVersion")


class StopPayload(StrictModel):
    reason: StopReason


class StopAckPayload(StrictModel):
    for_seq: Generation = Field(alias="forSeq")


class StoppedPayload(StrictModel):
    reason: StopReason
    forced: bool
    active_job_processes: Zero = Field(alias="activeJobProcesses")


class ControlErrorPayload(StrictModel):
    code: ControlErrorCode
    message: str = Field(min_length=1, max_length=256)


class FrameBase(StrictModel):
    protocol_version: ProtocolVersion = Field(alias="protocolVersion")
    runtime_id: Uuid = Field(alias="runtimeId")
    generation: Generation
    seq: Generation


class InitFrame(FrameBase):
    type: Literal["init"]
    payload: InitPayload = Field(repr=False)


class BootedFrame(FrameBase):
    type: Literal["booted"]
    payload: BootedPayload


class ReadyFrame(FrameBase):
    type: Literal["ready"]
    payload: ReadyPayload


class StopFrame(FrameBase):
    type: Literal["stop"]
    payload: StopPayload


class StopAckFrame(FrameBase):
    type: Literal["stop_ack"]
    payload: StopAckPayload


class StoppedFrame(FrameBase):
    type: Literal["stopped"]
    payload: StoppedPayload


class ErrorFrame(FrameBase):
    type: Literal["error"]
    payload: ControlErrorPayload = Field(repr=False)


type Frame = (
    InitFrame | BootedFrame | ReadyFrame | StopFrame | StopAckFrame | StoppedFrame | ErrorFrame
)
FRAME_ADAPTER: TypeAdapter[Frame] = TypeAdapter(Annotated[Frame, Field(discriminator="type")])
ALLOWED: dict[Direction, set[str]] = {
    "mainToSupervisor": {"init", "stop"},
    "supervisorToApi": {"init", "stop"},
    "apiToSupervisor": {"ready", "stop_ack", "error"},
    "supervisorToMain": {"booted", "ready", "stop_ack", "stopped", "error"},
}


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError()
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ProtocolError()


def _valid_unicode(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise ProtocolError()
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif isinstance(value, dict):
        for key, item in value.items():
            _valid_unicode(key, depth + 1)
            _valid_unicode(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _valid_unicode(item, depth + 1)


def parse_frame(raw: bytes) -> Frame:
    try:
        if (
            not raw
            or len(raw) + 1 > FRAME_LIMIT
            or b"\r" in raw
            or b"\n" in raw
            or raw.startswith(b"\xef\xbb\xbf")
        ):
            raise ProtocolError()
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_invalid_constant,
        )
        _valid_unicode(value)
        return FRAME_ADAPTER.validate_python(value, by_alias=True, by_name=False)
    except Exception:
        raise ProtocolError() from None


class FrameDecoder:
    def __init__(
        self, direction: Direction, runtime_id: str | None = None, generation: int | None = None
    ) -> None:
        if direction not in ALLOWED or (runtime_id is None) != (generation is None):
            raise ValueError("Invalid control channel configuration")
        if direction in ("apiToSupervisor", "supervisorToMain") and runtime_id is None:
            raise ValueError("Child output requires the expected instance identity")
        self.direction = direction
        self.runtime_id = runtime_id
        self.generation = generation
        self._seq = 1
        self._pending = bytearray()
        self._closed = False

    def _accept(self, frame: Frame) -> None:
        if frame.type not in ALLOWED[self.direction] or frame.seq != self._seq:
            raise ProtocolError()
        if self.direction in ("mainToSupervisor", "supervisorToApi"):
            if (frame.seq == 1) != (frame.type == "init"):
                raise ProtocolError()
        if self.runtime_id is None:
            self.runtime_id, self.generation = frame.runtime_id, frame.generation
        if frame.runtime_id != self.runtime_id or frame.generation != self.generation:
            raise ProtocolError()
        self._seq += 1

    def feed(self, chunk: bytes) -> list[Frame]:
        if self._closed:
            raise ProtocolError()
        frames: list[Frame] = []
        offset = 0
        try:
            while offset < len(chunk):
                end = chunk.find(b"\n", offset)
                stop = end if end >= 0 else len(chunk)
                if len(self._pending) + stop - offset + 1 > FRAME_LIMIT:
                    raise ProtocolError()
                self._pending.extend(chunk[offset:stop])
                if end < 0:
                    break
                frame = parse_frame(bytes(self._pending))
                self._pending.clear()
                self._accept(frame)
                frames.append(frame)
                offset = end + 1
            return frames
        except Exception:
            self._pending.clear()
            self._closed = True
            raise ProtocolError() from None

    def eof(self) -> None:
        if self._closed or self._pending:
            self._pending.clear()
            self._closed = True
            raise ProtocolError()
        self._closed = True


class FrameEncoder:
    def __init__(self, direction: Direction, runtime_id: str, generation: int) -> None:
        self._checker = FrameDecoder(direction, runtime_id, generation)
        self._seq = 1
        self._runtime_id = runtime_id
        self._generation = generation

    def encode(self, message_type: str, payload: dict[str, object]) -> bytes:
        try:
            value = {
                "protocolVersion": 1,
                "runtimeId": self._runtime_id,
                "generation": self._generation,
                "seq": self._seq,
                "type": message_type,
                "payload": payload,
            }
            raw = (
                json.dumps(
                    value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
                + b"\n"
            )
            self._checker.feed(raw)
            self._seq += 1
            return raw
        except Exception:
            raise ProtocolError() from None
