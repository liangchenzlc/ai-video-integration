"""SQLite's online backup API includes committed WAL pages without changing the source."""

import os
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from app.storage.database import connect, validate_project_schema
from app.storage.errors import ProjectError
from app.storage.paths import checked_path


def backup_project_database(directory: Path, project_id: str) -> Path:
    backup_dir = directory / "backups"
    backup_dir.mkdir(exist_ok=True)
    checked_path(backup_dir)
    target = backup_dir / (str(uuid4()) + ".sqlite3")
    with target.open("xb"):
        pass
    deadline = time.monotonic() + 30

    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() > deadline:
            raise ProjectError("BACKUP_FAILED", 503)

    try:
        with connect(directory / "project.sqlite3", "ro") as source:
            source.execute("BEGIN")
            if (
                source.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
                is None
            ):
                raise ProjectError("OBJECT_NOT_FOUND", 404)
            with connect(target) as destination:
                source.backup(destination, pages=256, progress=progress, sleep=0.02)
                policy = {
                    "foreign_keys": 1,
                    "journal_mode": "wal",
                    "synchronous": 2,
                    "busy_timeout": 3000,
                }
                for pragma, value in policy.items():
                    if destination.execute("PRAGMA " + pragma).fetchone()[0] != value:
                        raise ProjectError("BACKUP_FAILED", 503)
                if (
                    destination.execute(
                        "SELECT id FROM projects WHERE id=?", (project_id,)
                    ).fetchone()
                    is None
                ):
                    raise ProjectError("OBJECT_NOT_FOUND", 404)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ProjectError("BACKUP_FAILED", 503)
                if destination.execute("PRAGMA foreign_key_check").fetchone():
                    raise ProjectError("BACKUP_FAILED", 503)
                validate_project_schema(destination)
                destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        with target.open("r+b") as stream:
            os.fsync(stream.fileno())
    except ProjectError as error:
        if error.code == "OBJECT_NOT_FOUND":
            raise
        raise ProjectError("BACKUP_FAILED", 503) from None
    except (OSError, sqlite3.Error):
        # Even failed copies remain available for diagnosis. Never remove/replace the source.
        raise ProjectError("BACKUP_FAILED", 503) from None
    return target
