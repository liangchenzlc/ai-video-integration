"""Per-instance state. Construct explicitly; never serialize this object."""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from app import __version__
from app.api.v1.models import Generation, Uuid


@dataclass
class RuntimeContext:
    runtime_id: str
    generation: int
    token_bytes: bytes = field(repr=False)
    app_data_dir: Path
    mode: Literal["development", "production"]
    port: int
    api_version: Literal[1] = 1
    control_version: Literal[1] = 1
    backend_version: str = __version__
    started_monotonic: float = field(default_factory=time.monotonic)
    ready: bool = False

    def __post_init__(self) -> None:
        TypeAdapter(Uuid).validate_python(self.runtime_id, strict=True)
        self.generation = TypeAdapter(Generation).validate_python(self.generation)
        if (
            type(self.token_bytes) is not bytes
            or len(self.token_bytes) != 32
            or not self.app_data_dir.is_absolute()
        ):
            raise ValueError("Invalid runtime configuration")
        if self.mode not in ("development", "production"):
            raise ValueError("Invalid runtime mode")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Invalid runtime port")
