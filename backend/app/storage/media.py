"""Durable import state machine. Filesystem work never holds the service mutex."""

import errno
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.storage import tools
from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.paths import checked_path, relative_file

Json = dict[str, Any]
DATABASE = "project.sqlite3"


def dump(value: Json) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def require_space(directory: Path, size: int) -> None:
    if size < 1 or size > tools.MAX_BYTES:
        raise ProjectError("MEDIA_SIZE_LIMIT", 422)
    if shutil.disk_usage(directory).free < size + (size + 9) // 10 + 256 * 1024**2:
        raise ProjectError("INSUFFICIENT_DISK_SPACE", 507)


def media_row(db: sqlite3.Connection, identifier: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM media_files WHERE id=?", (identifier,)).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    return row  # type: ignore[no-any-return]


def dto(directory: Path, row: sqlite3.Row) -> Json:
    availability = row["availability"]
    if availability == "available":
        try:
            path = relative_file(directory, row["relative_path"])
            exists = path.is_file()
        except FileNotFoundError:
            exists = False
        if not exists:
            availability = "missing"
    return {
        "id": row["id"],
        "sha256": row["sha256"],
        "byteLength": row["byte_length"],
        "mime": row["mime"],
        "durationMs": row["duration_ms"],
        "width": row["width"],
        "height": row["height"],
        "availability": availability,
        "provenance": row["provenance"],
    }


class MediaExecutor:
    def __init__(self, mutex: Any, finished: Callable[[Path], None]) -> None:
        self.mutex = mutex
        self.finished = finished
        self.stop = threading.Event()
        self.pending: set[tuple[Path, str]] = set()
        self.project_ids: dict[tuple[Path, str], str] = {}
        self.cancellations: dict[tuple[Path, str], threading.Event] = {}
        self.tasks: queue.Queue[tuple[Path, str] | None] = queue.Queue()
        self.thread: threading.Thread | None = None
        # Fault injection only; production has no hook and enforces tools module defaults.
        self.fault_hook: Callable[[str], None] = lambda boundary: None

    def enqueue(self, directory: Path, job_id: str, project_id: str) -> None:
        if self.stop.is_set() or (directory, job_id) in self.pending:
            return
        self.pending.add((directory, job_id))
        self.project_ids[(directory, job_id)] = project_id
        self.cancellations[(directory, job_id)] = threading.Event()
        self.tasks.put((directory, job_id))
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="local-media", daemon=True)
            self.thread.start()

    def busy(self, directory: Path) -> bool:
        with self.mutex:
            return any(path == directory for path, _ in self.pending)

    def cancel(self, directory: Path, identifier: str) -> None:
        cancelled = self.cancellations.get((directory, identifier))
        if cancelled:
            cancelled.set()

    def recover(self, directory: Path, project_id: str) -> None:
        with connect(directory / DATABASE, "ro") as db:
            self._identity(db, project_id)
            rows = db.execute(
                "SELECT id FROM local_jobs WHERE state IN ('queued','running') "
                "ORDER BY active DESC,id"
            )
            identifiers = [row[0] for row in rows]
        for identifier in identifiers:
            self.enqueue(directory, identifier, project_id)

    def shutdown(self) -> None:
        self.stop.set()
        self.tasks.put(None)
        if self.thread:
            self.thread.join(timeout=2)

    def _loop(self) -> None:
        while (item := self.tasks.get()) is not None:
            directory, identifier = item
            try:
                if not self.stop.is_set():
                    self._execute(directory, identifier)
            except ProjectError as error:
                if not self.stop.is_set():
                    self._fail(directory, identifier, error.code)
            except (OSError, sqlite3.Error) as error:
                if not self.stop.is_set():
                    code = (
                        "INSUFFICIENT_DISK_SPACE"
                        if isinstance(error, OSError) and error.errno == errno.ENOSPC
                        else "STORAGE_UNAVAILABLE"
                    )
                    self._fail(directory, identifier, code)
            except Exception:
                # Unknown faults leave verified/renamed files available for recovery.
                if not self.stop.is_set():
                    self._fail(directory, identifier, "MEDIA_RECOVERY_REQUIRED", preserve=True)
            finally:
                with self.mutex:
                    self.pending.discard(item)
                    self.project_ids.pop(item, None)
                    self.cancellations.pop(item, None)
                    self.finished(directory)

    def _fail(self, directory: Path, identifier: str, code: str, *, preserve: bool = False) -> None:
        try:
            with self.mutex, connect(directory / DATABASE) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._identity(db, self.project_ids[(directory, identifier)])
                row = db.execute("SELECT * FROM local_jobs WHERE id=?", (identifier,)).fetchone()
                if row is None or row["state"] == "cancelled":
                    return
                if preserve:
                    db.execute(
                        "UPDATE local_jobs SET state='queued',active=0,error_code=? WHERE id=?",
                        (code, identifier),
                    )
                    return
                db.execute(
                    "UPDATE local_jobs SET state='failed',active=0,error_code=? WHERE id=?",
                    (code, identifier),
                )
                db.execute(
                    "UPDATE import_intents SET state='quarantined' WHERE operation_id=?",
                    (row["operation_id"],),
                )
                snapshot = json.loads(row["snapshot_json"])
                if not snapshot.get("relocate"):
                    db.execute(
                        "UPDATE media_files SET availability='quarantined' WHERE id=?",
                        (snapshot["mediaId"],),
                    )
        except (OSError, sqlite3.Error, ProjectError):
            # A disconnected/full disk must not kill the executor or erase durable intent.
            return

    def _check(self, directory: Path, identifier: str) -> None:
        if self.stop.is_set():
            raise ProjectError("JOB_INTERRUPTED")
        with connect(directory / DATABASE, "ro") as db:
            self._identity(db, self.project_ids[(directory, identifier)])
            row = db.execute("SELECT state FROM local_jobs WHERE id=?", (identifier,)).fetchone()
        if row is None or row[0] == "cancelled":
            raise ProjectError("JOB_CANCELLED")

    def _hash(self, path: Path, directory: Path, identifier: str) -> tuple[str, int]:
        checked_path(path, directory=False)
        digest = hashlib.sha256()
        length = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                self._check(directory, identifier)
                length += len(chunk)
                if length > tools.MAX_BYTES:
                    raise ProjectError("MEDIA_SIZE_LIMIT", 422)
                digest.update(chunk)
        return digest.hexdigest(), length

    def _execute(self, directory: Path, identifier: str) -> None:
        with self.mutex, connect(directory / DATABASE) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._identity(db, self.project_ids[(directory, identifier)])
            job = db.execute("SELECT * FROM local_jobs WHERE id=?", (identifier,)).fetchone()
            if job is None or job["state"] in {"cancelled", "succeeded", "failed"}:
                return
            intent = db.execute(
                "SELECT * FROM import_intents WHERE operation_id=?", (job["operation_id"],)
            ).fetchone()
            if intent is None:
                raise ProjectError("MEDIA_RECOVERY_REQUIRED")
            snapshot: Json = json.loads(job["snapshot_json"])
            if snapshot.get("projectId") != self.project_ids[(directory, identifier)]:
                raise ProjectError("MEDIA_RECOVERY_REQUIRED")
            db.execute("UPDATE local_jobs SET state='running',active=1 WHERE id=?", (identifier,))
        state = intent["state"]
        # Directory creation is validated before touching any children.
        for name in ("media", ".media-staging"):
            candidate = directory / name
            candidate.mkdir(exist_ok=True)
            checked_path(candidate)
        staging = relative_file(directory, intent["staging_path"])
        target = relative_file(directory, intent["target_path"])
        if state in {"verified", "renamed"}:
            candidate = target if target.exists() else staging
            if not candidate.is_file():
                raise ProjectError("MEDIA_RECOVERY_REQUIRED")
            digest, length = self._hash(candidate, directory, identifier)
            if digest != intent["expected_hash"] or length != snapshot["byteLength"]:
                raise ProjectError("MEDIA_HASH_MISMATCH")
        elif state == "planned":
            source = checked_path(Path(snapshot["sourcePath"]), directory=False)
            require_space(directory, source.stat().st_size)
            if source.suffix.lower() not in tools.EXTENSIONS:
                raise ProjectError("MEDIA_FORMAT_UNSUPPORTED", 422)
            # Existing staging is never truncated, including an unrecognized leftover.
            with self.mutex, connect(directory / DATABASE) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._assert_running(db, directory, identifier)
                db.execute("UPDATE import_intents SET state='writing' WHERE id=?", (intent["id"],))
            digest_object = hashlib.sha256()
            length = 0
            with source.open("rb") as original, staging.open("xb") as copied:
                before = os.fstat(original.fileno())
                while chunk := original.read(1024 * 1024):
                    self._check(directory, identifier)
                    length += len(chunk)
                    if length > tools.MAX_BYTES:
                        raise ProjectError("MEDIA_SIZE_LIMIT", 422)
                    copied.write(chunk)
                    digest_object.update(chunk)
                    self.fault_hook("copy_chunk")
                copied.flush()
                os.fsync(copied.fileno())
                after = os.fstat(original.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ProjectError("MEDIA_SOURCE_CHANGED")
            digest = digest_object.hexdigest()
            if snapshot.get("expectedHash") and snapshot["expectedHash"] != digest:
                raise ProjectError("MEDIA_HASH_MISMATCH")
            metadata = tools.probe_media(
                Path(snapshot["ffmpegPath"]),
                staging,
                self.stop,
                self.cancellations.get((directory, identifier)),
            )
            self._check(directory, identifier)
            snapshot.update(metadata)
            snapshot.update({"sha256": digest, "byteLength": length})
            with self.mutex, connect(directory / DATABASE) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._assert_running(db, directory, identifier)
                db.execute(
                    "UPDATE import_intents SET state='verified',expected_hash=? WHERE id=?",
                    (digest, intent["id"]),
                )
                db.execute(
                    "UPDATE local_jobs SET snapshot_json=? WHERE id=?", (dump(snapshot), identifier)
                )
            self.fault_hook("verified")
        else:
            # A partial copy has no verified hash. Preserve it and require an explicit retry.
            raise ProjectError("MEDIA_RECOVERY_REQUIRED")
        self._check(directory, identifier)
        # Serialize rename and registration with cancellation, without probe/hash/copy here.
        with self.mutex:
            with connect(directory / DATABASE, "ro") as db:
                self._assert_running(db, directory, identifier)
            if not target.exists():
                if os.name == "nt":
                    staging.rename(target)
                else:
                    os.link(staging, target)
                    staging.unlink()
            elif state not in {"verified", "renamed"}:
                raise ProjectError("MEDIA_RECOVERY_REQUIRED")
            with connect(directory / DATABASE) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._assert_running(db, directory, identifier)
                db.execute("UPDATE import_intents SET state='renamed' WHERE id=?", (intent["id"],))
            self.fault_hook("renamed")
            with connect(directory / DATABASE) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._assert_running(db, directory, identifier)
                if snapshot.get("relocate"):
                    db.execute(
                        "UPDATE media_files SET relative_path=?,availability='available' "
                        "WHERE id=? AND sha256=?",
                        (intent["target_path"], snapshot["mediaId"], digest),
                    )
                else:
                    db.execute(
                        "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            snapshot["mediaId"],
                            intent["target_path"],
                            digest,
                            length,
                            snapshot["mime"],
                            snapshot["durationMs"],
                            snapshot["width"],
                            snapshot["height"],
                            "available",
                            "imported",
                            dump(
                                {
                                    "sourcePath": snapshot["sourcePath"],
                                    "purpose": snapshot["purpose"],
                                }
                            ),
                        ),
                    )
                db.execute(
                    "UPDATE import_intents SET state='registered' WHERE id=?", (intent["id"],)
                )
                db.execute(
                    "UPDATE local_jobs SET state='succeeded',active=0,result_id=?,"
                    "error_code=NULL WHERE id=?",
                    (snapshot["mediaId"], identifier),
                )
                db.execute("UPDATE projects SET event_sequence=event_sequence+1")

    @staticmethod
    def _identity(db: sqlite3.Connection, project_id: str) -> None:
        if db.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)

    def _assert_running(self, db: sqlite3.Connection, directory: Path, identifier: str) -> None:
        self._identity(db, self.project_ids[(directory, identifier)])
        state = db.execute("SELECT state FROM local_jobs WHERE id=?", (identifier,)).fetchone()
        if state is None or state[0] != "running":
            raise ProjectError("JOB_CANCELLED")
