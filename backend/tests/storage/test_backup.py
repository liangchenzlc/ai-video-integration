import sqlite3
from typing import Any

import pytest
from app.storage import backup
from app.storage.database import connect
from tests.storage.test_media import media_project as media_project


def test_invalid_backup_is_retained_without_touching_source(
    media_project: Any, monkeypatch: Any
) -> None:
    service, directory, args = media_project
    validate = backup.validate_project_schema

    def corrupt_copy(db: sqlite3.Connection) -> None:
        db.execute("CREATE TABLE unknown_corruption(id TEXT)")
        db.commit()
        validate(db)

    monkeypatch.setattr(backup, "validate_project_schema", corrupt_copy)
    with pytest.raises(Exception, match="BACKUP_FAILED"):
        service.backup_project(*args)
    copies = list((directory / "backups").glob("*.sqlite3"))
    assert len(copies) == 1
    with connect(directory / "project.sqlite3", "ro") as original:
        validate(original)
        assert original.execute("SELECT name FROM projects").fetchone()[0] == "A project"
    with connect(copies[0], "ro") as copied:
        assert copied.execute(
            "SELECT name FROM sqlite_schema WHERE name='unknown_corruption'"
        ).fetchone()


def test_backup_destination_enforces_connection_policy(
    media_project: Any, monkeypatch: Any
) -> None:
    service, _, args = media_project
    validate = backup.validate_project_schema
    observed: list[dict[str, Any]] = []

    def inspect(db: sqlite3.Connection) -> None:
        observed.append(
            {
                name: db.execute("PRAGMA " + name).fetchone()[0]
                for name in ("foreign_keys", "journal_mode", "synchronous", "busy_timeout")
            }
        )
        validate(db)

    monkeypatch.setattr(backup, "validate_project_schema", inspect)
    service.backup_project(*args)
    assert observed == [
        {"foreign_keys": 1, "journal_mode": "wal", "synchronous": 2, "busy_timeout": 3000}
    ]
