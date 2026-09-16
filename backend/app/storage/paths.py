import ctypes
import os
import stat
from pathlib import Path, PurePosixPath

from app.storage.errors import ProjectError


def checked_path(path: Path, *, directory: bool = True) -> Path:
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ProjectError("UNSAFE_PROJECT_PATH", 403)
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & (0x400 | 0x1000 | 0x40000 | 0x400000):
            raise ProjectError("UNSAFE_PROJECT_PATH", 403)
    resolved = path.resolve(strict=True)
    if directory and not resolved.is_dir():
        raise ProjectError("GRANT_REJECTED", 403)
    if os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(str(resolved.anchor)) == 4:
        raise ProjectError("UNSAFE_PROJECT_PATH", 403)
    for part in resolved.parts:
        if part.casefold() in {"onedrive", "dropbox", "google drive", "googledrive", "iclouddrive"}:
            raise ProjectError("UNSAFE_PROJECT_PATH", 403)
        if part.casefold().startswith("onedrive - "):
            raise ProjectError("UNSAFE_PROJECT_PATH", 403)
    for key in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        synced = os.environ.get(key)
        if synced and resolved.is_relative_to(Path(synced).resolve()):
            raise ProjectError("UNSAFE_PROJECT_PATH", 403)
    return resolved


def relative_file(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if (
        not relative
        or parts.is_absolute()
        or "\\" in relative
        or ":" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ProjectError("UNSAFE_PROJECT_PATH", 403)
    target = root.joinpath(*parts.parts)
    checked_path(target if target.exists() else target.parent, directory=False)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ProjectError("UNSAFE_PROJECT_PATH", 403)
    return target
