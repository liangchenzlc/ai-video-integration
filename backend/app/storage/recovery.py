"""Inspect SQLite recovery sidecars before SQLite can rewrite or discard them."""

import struct
import sys
from pathlib import Path

from app.storage.errors import ProjectError
from app.storage.paths import checked_path


def _reject() -> None:
    raise ProjectError("PROJECT_RECOVERY_REQUIRED")


def _checksum(data: bytes, endian: str, seed: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    first, second = seed
    for left, right in struct.iter_unpack(endian + "II", data):
        first = (first + left + second) & 0xFFFFFFFF
        second = (second + right + first) & 0xFFFFFFFF
    return first, second


def validate_recovery_sidecars(database: Path) -> None:
    """Fail closed on malformed/torn/unknown sidecars, preserving every original byte.

    Called under the project OS lock before opening either the staging or published DB.
    WAL headers and every frame checksum are verified; SHM must identify the same WAL.
    Unknown or interrupted formats remain available for explicit manual recovery.
    """
    wal = Path(str(database) + "-wal")
    shm = Path(str(database) + "-shm")
    for candidate in (wal, shm):
        if candidate.exists() or candidate.is_symlink():
            checked_path(candidate, directory=False)
            if not candidate.is_file() or not database.is_file():
                _reject()
    header = b""
    page_size = 0
    frames = 0
    last_commit = 0
    commit_checksum = (0, 0)
    if wal.exists() and wal.stat().st_size:
        with wal.open("rb") as stream:
            header = stream.read(32)
            if len(header) != 32:
                _reject()
            magic, version, page_size = struct.unpack(">III", header[:12])
            if (
                magic not in {0x377F0682, 0x377F0683}
                or version != 3007000
                or page_size < 512
                or page_size > 65536
                or page_size & (page_size - 1)
            ):
                _reject()
            endian = ">" if magic & 1 else "<"
            checksum = _checksum(header[:24], endian)
            if checksum != struct.unpack(">II", header[24:32]):
                _reject()
            while frame := stream.read(24):
                content = stream.read(page_size)
                if (
                    len(frame) != 24
                    or len(content) != page_size
                    or frame[8:16] != header[16:24]
                    or struct.unpack(">I", frame[:4])[0] == 0
                ):
                    _reject()
                checksum = _checksum(frame[:8] + content, endian, checksum)
                if checksum != struct.unpack(">II", frame[16:24]):
                    _reject()
                frames += 1
                if struct.unpack(">I", frame[4:8])[0]:
                    last_commit, commit_checksum = frames, checksum
    if shm.exists() and shm.stat().st_size:
        if shm.stat().st_size % 32768:
            _reject()
        with shm.open("rb") as stream:
            index = stream.read(96)
        native = "<" if sys.byteorder == "little" else ">"
        if (
            len(index) != 96
            or index[:48] != index[48:96]
            or struct.unpack(native + "I", index[:4])[0] != 3007000
            or index[12] != 1
            or _checksum(index[:40], native) != struct.unpack(native + "II", index[40:48])
        ):
            _reject()
        if not header:
            # A read-only SQLite connection may leave an initialized empty WAL index.
            if index[13:40] != bytes(27):
                _reject()
            return
        if index[13] != (header[3] & 1) or index[32:40] != header[16:24]:
            _reject()
        size = struct.unpack(native + "H", index[14:16])[0]
        if (65536 if size == 1 else size) != page_size:
            _reject()
        if (
            struct.unpack(native + "I", index[16:20])[0] != last_commit
            or struct.unpack(native + "II", index[24:32]) != commit_checksum
        ):
            _reject()
