import os
import sys
from pathlib import Path

from app.storage.paths import checked_path


class ProjectLock:
    """A held OS byte lock, including between processes on Windows."""

    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    @classmethod
    def acquire(cls, directory: Path) -> "ProjectLock | None":
        checked_path(directory)
        lock_path = directory / ".ai-video-write.lock"
        if lock_path.exists() or lock_path.is_symlink():
            checked_path(lock_path, directory=False)
        descriptor = os.open(directory / ".ai-video-write.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            return None
        return cls(descriptor)

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1
