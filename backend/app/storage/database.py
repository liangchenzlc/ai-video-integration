import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import Literal

from app.storage.errors import ProjectError
from app.storage.paths import checked_path


@contextmanager
def connect(path: Path, mode: Literal["ro", "rw", "rwc"] = "rw") -> Iterator[sqlite3.Connection]:
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        if candidate.exists() or candidate.is_symlink():
            checked_path(candidate, directory=False)
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=" + mode, uri=True, timeout=3)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if mode == "ro":
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                raise sqlite3.DatabaseError("Unsupported journal mode")
        else:
            db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=3000")
        if mode == "ro":
            db.execute("PRAGMA query_only=ON")
        yield db
    finally:
        db.close()


def initialize_application(path: Path) -> None:
    with connect(path, "rwc") as db, db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS recent_projects (
          project_id TEXT PRIMARY KEY, directory TEXT NOT NULL UNIQUE,
          last_opened_at TEXT NOT NULL, name TEXT NOT NULL) STRICT;
        CREATE TABLE IF NOT EXISTS global_operations (
          id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, operation_name TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('prepared','committed','accepted')),
          resource_id TEXT NOT NULL, receipt_json TEXT CHECK(receipt_json IS NULL
            OR json_valid(receipt_json)), directory TEXT NOT NULL,
          request_json TEXT NOT NULL CHECK(json_valid(request_json))) STRICT;
        CREATE TABLE IF NOT EXISTS settings (
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          revision INTEGER NOT NULL CHECK(revision>=0), ffmpeg_path TEXT,
          ffmpeg_probe_json TEXT CHECK(ffmpeg_probe_json IS NULL
            OR json_valid(ffmpeg_probe_json))) STRICT;
        INSERT OR IGNORE INTO settings(singleton,revision) VALUES(1,0);
        CREATE TABLE IF NOT EXISTS credentials (
          id TEXT PRIMARY KEY, provider_id TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL CHECK(kind IN ('api_key','oss')),
          dpapi_ciphertext BLOB NOT NULL,
          masked_suffix TEXT NOT NULL CHECK(length(masked_suffix)=4)) STRICT;
        CREATE TABLE IF NOT EXISTS capabilities (
          id TEXT PRIMARY KEY, version TEXT NOT NULL,
          profile_json TEXT NOT NULL CHECK(json_valid(profile_json)),
          checked_at TEXT NOT NULL) STRICT;
        CREATE TABLE IF NOT EXISTS storage_profiles (
          id TEXT PRIMARY KEY, provider_id TEXT NOT NULL UNIQUE, bucket TEXT NOT NULL,
          region TEXT NOT NULL, credential_id TEXT NOT NULL REFERENCES credentials(id),
          retention_hours INTEGER NOT NULL CHECK(retention_hours BETWEEN 1 AND 168)) STRICT;
        CREATE TABLE IF NOT EXISTS global_jobs (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
          result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json))) STRICT;
        """)


def initialize_project(path: Path) -> None:
    with connect(path, "rwc") as db:
        db.executescript((Path(__file__).parent / "migration_002.sql").read_text("utf-8"))
        with db:
            db.execute((Path(__file__).parent / "migration_003.sql").read_text("utf-8"))
            db.execute("PRAGMA user_version=3")
            _apply_004(db)
            _apply_005(db)


def _apply_004(db: sqlite3.Connection) -> None:
    # executescript implicitly commits: execute complete SQL statements individually instead.
    statement = ""
    for line in (Path(__file__).parent / "migration_004.sql").read_text("utf-8").splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ""
    db.execute("PRAGMA user_version=4")


def _apply_005(db: sqlite3.Connection) -> None:
    statement = ""
    for line in (Path(__file__).parent / "migration_005.sql").read_text("utf-8").splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ""
    db.execute("PRAGMA user_version=5")


def _schema(db: sqlite3.Connection) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (kind, name, table, " ".join(sql.split()))
        for kind, name, table, sql in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY name"
        )
    )


@cache
def _expected_project_schema(version: int) -> tuple[tuple[str, ...], ...]:
    # An isolated, empty template captures columns, defaults, constraints, FKs and indexes.
    # It never opens or migrates user data.
    db = sqlite3.connect(":memory:")
    try:
        db.executescript((Path(__file__).parent / "migration_002.sql").read_text("utf-8"))
        if version >= 3:
            db.execute((Path(__file__).parent / "migration_003.sql").read_text("utf-8"))
        if version >= 4:
            _apply_004(db)
        if version >= 5:
            _apply_005(db)
        return _schema(db)
    finally:
        db.close()


def validate_project_schema(db: sqlite3.Connection) -> None:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in {2, 3, 4, 5}:
        raise ProjectError("PROJECT_VERSION_UNSUPPORTED")
    if _schema(db) != _expected_project_schema(version):
        raise ProjectError("PROJECT_CORRUPT")


def migrate_project(path: Path, project_id: str) -> None:
    """Caller holds the project lock and has completed an online backup."""
    try:
        with connect(path) as db, db:
            db.execute("BEGIN IMMEDIATE")
            validate_project_schema(db)
            if db.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone() is None:
                raise ProjectError("OBJECT_NOT_FOUND", 404)
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 5:
                return
            if version == 2:
                db.execute((Path(__file__).parent / "migration_003.sql").read_text("utf-8"))
            if version < 4:
                _apply_004(db)
            _apply_005(db)
            validate_project_schema(db)
    except ProjectError as error:
        if error.code == "OBJECT_NOT_FOUND":
            raise
        raise ProjectError("PROJECT_MIGRATION_FAILED", 503) from None
    except (OSError, sqlite3.Error):
        raise ProjectError("PROJECT_MIGRATION_FAILED", 503) from None
