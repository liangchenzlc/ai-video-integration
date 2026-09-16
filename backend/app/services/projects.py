"""Project creation, durable recovery and window-owned in-memory sessions."""

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Concatenate, cast
from uuid import UUID, uuid4

from app.services.tasks import TaskService
from app.services.versions import VersionService
from app.storage import capabilities, drafts, media, settings, tools
from app.storage.backup import backup_project_database
from app.storage.database import (
    connect,
    initialize_application,
    initialize_project,
    migrate_project,
    validate_project_schema,
)
from app.storage.errors import ProjectError
from app.storage.locking import ProjectLock
from app.storage.paths import checked_path, relative_file
from app.storage.recovery import validate_recovery_sidecars

Json = dict[str, Any]
DATABASE = "project.sqlite3"
MARKER = ".ai-video-project.json"


def now() -> str:
    return datetime.now(UTC).isoformat()


def canonical(value: Json) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise ProjectError("VALIDATION_FAILED", 422)
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ProjectError("VALIDATION_FAILED", 422)
    return value


def guarded[**P, R](
    method: Callable[Concatenate["ProjectService", P], R],
) -> Callable[Concatenate["ProjectService", P], R]:
    @wraps(method)
    def call(self: "ProjectService", /, *args: P.args, **kwargs: P.kwargs) -> R:
        with self._mutex:
            try:
                return method(self, *args, **kwargs)
            except ProjectError:
                raise
            except (OSError, sqlite3.Error):
                raise ProjectError("STORAGE_UNAVAILABLE", 503) from None
            except (KeyError, TypeError, ValueError):
                raise ProjectError("VALIDATION_FAILED", 422) from None

    return call


@dataclass
class Grant:
    directory: Path
    purpose: str
    window_id: int
    expires: float


@dataclass
class Session:
    directory: Path
    project_id: str
    window_id: int
    lock: ProjectLock | None


class ProjectService:
    def __init__(
        self,
        app_data_dir: Path,
        *,
        capability_profiles: list[Json] | None = None,
        free_checkers: dict[str, capabilities.FreeChecker] | None = None,
    ) -> None:
        self.app_data_dir = app_data_dir
        self._mutex = threading.RLock()
        self._grants: dict[str, Grant] = {}
        self._used_grant_ids: set[str] = set()
        self._grant_operations: dict[str, tuple[str, Json]] = {}
        self._tool_operations: dict[str, tuple[str, Future[Json]]] = {}
        self._sessions: dict[str, Session] = {}
        self._detached_locks: dict[Path, ProjectLock] = {}
        self._media = media.MediaExecutor(self._mutex, self._media_finished)
        self._tasks = TaskService(self)
        self._versions = VersionService(self)
        self._application = app_data_dir / "application.sqlite3"
        self._settings = settings.SettingsStore(self._application)
        self._free_checkers = dict(free_checkers or {})
        try:
            app_data_dir.mkdir(parents=True, exist_ok=True)
            initialize_application(self._application)
            capabilities.initialize(self._application, capability_profiles or [])
            with connect(self._application) as db:
                prepared = db.execute("SELECT * FROM global_operations WHERE state='prepared'")
                rows = prepared.fetchall()
            for row in rows:
                try:
                    self._recover(row)
                except (ProjectError, OSError, sqlite3.Error, ValueError):
                    # Uncertain leftovers stay intact. Explicit lookup reports recovery required.
                    continue
        except (OSError, sqlite3.Error):
            raise ProjectError("STORAGE_UNAVAILABLE", 503) from None

    @guarded
    def register_grant(self, command: Json, window_id: int) -> Json:
        operation = uuid(command["clientOperationId"])
        digest = hashlib.sha256(canonical(command).encode()).hexdigest()
        payload = command["payload"]
        if type(window_id) is not int or window_id < 1 or payload["windowId"] != window_id:
            raise ProjectError("GRANT_REJECTED", 403)
        previous = self._grant_operations.get(operation)
        if previous:
            if previous[0] != digest:
                raise ProjectError("OPERATION_ID_REUSED")
            return dict(previous[1])
        if command["expectedRevision"] != 0:
            raise ProjectError("REVISION_CONFLICT")
        identifier = uuid(payload["grantId"])
        if identifier in self._used_grant_ids or payload["purpose"] not in {
            "createProject",
            "openProject",
            "importMedia",
            "ffmpeg",
        }:
            raise ProjectError("GRANT_REJECTED", 403)
        is_directory = payload["purpose"] in {"createProject", "openProject"}
        directory = checked_path(Path(payload["path"]), directory=is_directory)
        if not is_directory and not directory.is_file():
            raise ProjectError("GRANT_REJECTED", 403)
        self._grants[identifier] = Grant(
            directory, payload["purpose"], window_id, time.monotonic() + 300
        )
        self._used_grant_ids.add(identifier)
        receipt = self._receipt(operation, identifier, 0)
        self._grant_operations[operation] = (digest, receipt)
        return dict(receipt)

    def _grant(self, identifier: str, purpose: str, window_id: int) -> Path:
        grant = self._grants.get(uuid(identifier))
        if (
            grant is None
            or grant.window_id != window_id
            or grant.purpose != purpose
            or time.monotonic() >= grant.expires
        ):
            raise ProjectError("GRANT_REJECTED", 403)
        is_directory = purpose in {"createProject", "openProject"}
        directory = checked_path(grant.directory, directory=is_directory)
        if not is_directory and not directory.is_file():
            raise ProjectError("GRANT_REJECTED", 403)
        del self._grants[identifier]
        return directory

    @staticmethod
    def _receipt(operation: str, resource: str, revision: int = 1) -> Json:
        return {
            "operationId": operation,
            "resourceId": resource,
            "committedRevision": revision,
            "state": "committed",
        }

    @guarded
    def create_project(self, command: Json, window_id: int) -> Json:
        operation = uuid(command["clientOperationId"])
        serialized = canonical(command)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        with connect(self._application) as db:
            previous = db.execute(
                "SELECT * FROM global_operations WHERE id=?", (operation,)
            ).fetchone()
        if previous:
            if previous["request_hash"] != digest or previous["operation_name"] != "createProject":
                raise ProjectError("OPERATION_ID_REUSED")
            return self._recover(previous)
        if command["expectedRevision"] != 0:
            raise ProjectError("REVISION_CONFLICT")
        payload = command["payload"]
        self._validate_project(payload)
        directory = self._grant(payload["directoryGrantId"], "createProject", window_id)
        if any(directory.iterdir()):
            raise ProjectError("DIRECTORY_NOT_EMPTY")
        project_id = str(uuid4())
        with connect(self._application) as db, db:
            db.execute(
                """INSERT INTO global_operations
                (id,request_hash,operation_name,state,resource_id,directory,request_json)
                VALUES (?,?,'createProject','prepared',?,?,?)""",
                (operation, digest, project_id, str(directory), serialized),
            )
        marker = {"projectId": project_id, "operationId": operation, "requestHash": digest}
        # Exclusive creation cannot replace user data, including a raced-in marker.
        with (directory / MARKER).open("x", encoding="utf-8") as stream:
            stream.write(canonical(marker))
            stream.flush()
            os.fsync(stream.fileno())
        with connect(self._application) as db:
            row = db.execute("SELECT * FROM global_operations WHERE id=?", (operation,)).fetchone()
        return self._recover(row)

    @staticmethod
    def _validate_project(payload: Json) -> None:
        name = payload["name"]
        fps = payload["fps"]
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 120
            or payload["aspect"] not in {"16:9", "9:16"}
            or payload["resolution"] not in {"720p", "1080p"}
            or type(fps["numerator"]) is not int
            or fps["numerator"] not in {24, 25, 30}
            or type(fps["denominator"]) is not int
            or fps["denominator"] != 1
            or type(payload["targetMs"]) is not int
            or not 1 <= payload["targetMs"] <= 9007199254740991
        ):
            raise ProjectError("VALIDATION_FAILED", 422)

    def _recover(self, row: sqlite3.Row) -> Json:
        if row["state"] == "committed":
            receipt: Json = json.loads(row["receipt_json"])
            return receipt
        directory = checked_path(Path(row["directory"]))
        if not (directory / MARKER).is_file():
            raise ProjectError("PROJECT_RECOVERY_REQUIRED")
        lock = ProjectLock.acquire(directory)
        if lock is None:
            raise ProjectError("PROJECT_BUSY")
        try:
            return self._recover_locked(row)
        finally:
            lock.close()

    def _recover_locked(self, row: sqlite3.Row) -> Json:
        directory = checked_path(Path(row["directory"]))
        marker_path = directory / MARKER
        if not marker_path.is_file():
            raise ProjectError("PROJECT_RECOVERY_REQUIRED")
        checked_path(marker_path, directory=False)
        expected = {
            "projectId": row["resource_id"],
            "operationId": row["id"],
            "requestHash": row["request_hash"],
        }
        try:
            if json.loads(marker_path.read_text("utf-8")) != expected:
                raise ProjectError("PROJECT_RECOVERY_REQUIRED")
        except (ValueError, UnicodeError):
            raise ProjectError("PROJECT_RECOVERY_REQUIRED") from None
        command: Json = json.loads(row["request_json"])
        if hashlib.sha256(canonical(command).encode()).hexdigest() != row["request_hash"]:
            raise ProjectError("PROJECT_RECOVERY_REQUIRED")
        payload = command["payload"]
        self._validate_project(payload)
        staging = directory / (".ai-video-staging-" + row["id"])
        database = directory / DATABASE
        allowed = {
            MARKER,
            staging.name,
            DATABASE,
            DATABASE + "-wal",
            DATABASE + "-shm",
            ".ai-video-write.lock",
        }
        if any(entry.name not in allowed for entry in directory.iterdir()):
            raise ProjectError("PROJECT_RECOVERY_REQUIRED")
        validate_recovery_sidecars(database)
        if staging.exists():
            checked_path(staging)
            if any(
                p.name not in {DATABASE, DATABASE + "-wal", DATABASE + "-shm"}
                for p in staging.iterdir()
            ):
                raise ProjectError("PROJECT_RECOVERY_REQUIRED")
            validate_recovery_sidecars(staging / DATABASE)
        receipt = self._receipt(row["id"], row["resource_id"])
        if not database.exists():
            if not staging.exists():
                staging.mkdir()
                initialize_project(staging / DATABASE)
                with connect(staging / DATABASE) as db, db:
                    db.execute(
                        """INSERT INTO projects
                        (id,name,format_version,revision,aspect,resolution,fps_n,fps_d,target_ms,saved_at)
                        VALUES (?,?,1,1,?,?,?,?,?,?)""",
                        (
                            row["resource_id"],
                            payload["name"],
                            payload["aspect"],
                            payload["resolution"],
                            payload["fps"]["numerator"],
                            payload["fps"]["denominator"],
                            payload["targetMs"],
                            now(),
                        ),
                    )
                    db.execute(
                        "INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                        (
                            row["id"],
                            row["request_hash"],
                            "createProject",
                            1,
                            row["resource_id"],
                            canonical(receipt),
                            now(),
                        ),
                    )
                with connect(staging / DATABASE) as db:
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            checked_path(staging)
            if any(
                p.name not in {DATABASE, DATABASE + "-wal", DATABASE + "-shm"}
                for p in staging.iterdir()
            ):
                raise ProjectError("PROJECT_RECOVERY_REQUIRED")
            self._verify_created(staging / DATABASE, row)
            # A crashed writer can leave the committed project row in WAL only.
            # Verify first, then checkpoint while holding the exclusive project lock.
            with connect(staging / DATABASE) as db:
                if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                    raise ProjectError("PROJECT_BUSY")
            with (staging / DATABASE).open("r+b") as stream:
                os.fsync(stream.fileno())
            # On Windows rename fails if destination already exists (never overwrites).
            if os.name == "nt":
                (staging / DATABASE).rename(database)
            else:
                os.link(staging / DATABASE, database)
                (staging / DATABASE).unlink()
        self._verify_created(database, row)
        with connect(self._application) as db, db:
            db.execute(
                "UPDATE global_operations SET state='committed',receipt_json=? WHERE id=?",
                (canonical(receipt), row["id"]),
            )
            self._recent(db, row["resource_id"], directory, payload["name"])
        return receipt

    def _verify_created(self, database: Path, operation: sqlite3.Row) -> None:
        project = self._read_project(database, True)
        if project["id"] != operation["resource_id"]:
            raise ProjectError("PROJECT_RECOVERY_REQUIRED")
        with connect(database, "ro") as db:
            row = db.execute(
                "SELECT request_hash FROM operations WHERE id=?", (operation["id"],)
            ).fetchone()
            if row is None or row["request_hash"] != operation["request_hash"]:
                raise ProjectError("PROJECT_RECOVERY_REQUIRED")

    @staticmethod
    def _read_project(database: Path, read_only: bool) -> Json:
        if not database.is_file():
            raise ProjectError("PROJECT_NOT_FOUND", 404)
        checked_path(database, directory=False)
        try:
            with connect(database, "ro") as db:
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ProjectError("PROJECT_CORRUPT")
                if db.execute("PRAGMA user_version").fetchone()[0] not in {2, 3, 4, 5}:
                    raise ProjectError("PROJECT_VERSION_UNSUPPORTED")
                validate_project_schema(db)
                if db.execute("PRAGMA foreign_key_check").fetchone():
                    raise ProjectError("PROJECT_CORRUPT")
                rows = db.execute("SELECT * FROM projects").fetchall()
                if len(rows) != 1:
                    raise ProjectError("PROJECT_CORRUPT")
                row = rows[0]
                if row["format_version"] != 1:
                    raise ProjectError("PROJECT_VERSION_UNSUPPORTED")
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "revision": row["revision"],
                    "eventSequence": row["event_sequence"],
                    "formatVersion": row["format_version"],
                    "aspect": row["aspect"],
                    "resolution": row["resolution"],
                    "fps": {"numerator": row["fps_n"], "denominator": row["fps_d"]},
                    "targetMs": row["target_ms"],
                    "budgetMicroCny": row["budget_micro_cny"],
                    "executionMode": row["execution_mode"]
                    if "execution_mode" in row.keys()
                    else None,
                    "savedAt": row["saved_at"],
                    "readOnly": read_only,
                }
        except (sqlite3.DatabaseError, IndexError, KeyError, ValueError):
            raise ProjectError("PROJECT_CORRUPT") from None

    @staticmethod
    def _recent(db: sqlite3.Connection, project_id: str, directory: Path, name: str) -> None:
        db.execute(
            "DELETE FROM recent_projects WHERE directory=? AND project_id<>?",
            (str(directory), project_id),
        )
        db.execute(
            """INSERT INTO recent_projects VALUES (?,?,?,?)
                   ON CONFLICT(project_id) DO UPDATE SET directory=excluded.directory,
                   last_opened_at=excluded.last_opened_at,name=excluded.name""",
            (project_id, str(directory), now(), name),
        )

    @guarded
    def open_project(self, command: Json, window_id: int) -> Json:
        if command["requestedMode"] not in {"read", "write"}:
            raise ProjectError("VALIDATION_FAILED", 422)
        directory = self._grant(command["directoryGrantId"], "openProject", window_id)
        project = self._read_project(directory / DATABASE, True)
        for identifier, session in self._sessions.items():
            if (
                session.window_id == window_id
                and session.directory == directory
                and session.project_id == project["id"]
                and (command["requestedMode"] == "write" or session.lock is None)
            ):
                project["readOnly"] = session.lock is None
                return {
                    "projectId": project["id"],
                    "projectSessionId": identifier,
                    "mode": "read" if session.lock is None else "write",
                    "project": project,
                }
        lock = None
        if command["requestedMode"] == "write":
            lock = self._detached_locks.pop(directory, None) or ProjectLock.acquire(directory)
        opened_identifier: str | None = None
        try:
            if lock is not None:
                with connect(directory / DATABASE, "ro") as db:
                    version = db.execute("PRAGMA user_version").fetchone()[0]
                if version < 5:
                    backup_project_database(directory, project["id"])
                    migrate_project(directory / DATABASE, project["id"])
            project["readOnly"] = lock is None
            identifier = str(uuid4())
            opened_identifier = identifier
            with connect(self._application) as db, db:
                self._recent(db, project["id"], directory, project["name"])
            self._sessions[identifier] = Session(directory, project["id"], window_id, lock)
            self._tasks.remember_project(directory, project["id"])
            if lock is not None:
                self._media.recover(directory, project["id"])
                self._tasks.executor.recover(directory, project["id"])
            return {
                "projectId": project["id"],
                "projectSessionId": identifier,
                "mode": "read" if lock is None else "write",
                "project": project,
            }
        except BaseException:
            if opened_identifier is not None:
                self._sessions.pop(opened_identifier, None)
            if lock:
                if self._media.busy(directory) or self._tasks.executor.busy(directory):
                    self._detached_locks[directory] = lock
                else:
                    lock.close()
            raise

    @guarded
    def get_project(self, project_id: str, session_id: str, window_id: int) -> Json:
        session = self._session(session_id, window_id)
        if project_id != session.project_id:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        project = self._read_project(session.directory / DATABASE, session.lock is None)
        if project["id"] != session.project_id:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        return project

    def _session(self, session_id: str, window_id: int) -> Session:
        session = self._sessions.get(session_id)
        if session is None or session.window_id != window_id:
            raise ProjectError("SESSION_EXPIRED", 401)
        return session

    def _draft_session(self, project_id: str, session_id: str, window_id: int) -> Session:
        session = self._session(session_id, window_id)
        if project_id != session.project_id:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        return session

    @staticmethod
    def _project_row(db: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        return cast(sqlite3.Row, row)

    @guarded
    def get_budget(self, project_id: str, session_id: str, window_id: int) -> Json:
        return self._tasks.get_budget(project_id, session_id, window_id)

    @guarded
    def set_budget(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        return self._tasks.set_budget(project_id, session_id, window_id, command)

    @guarded
    def plan_task(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        return self._tasks.plan_task(project_id, session_id, window_id, command)

    @guarded
    def get_task_plan(self, project_id: str, session_id: str, window_id: int, plan_id: str) -> Json:
        return self._tasks.get_task_plan(project_id, session_id, window_id, plan_id)

    @guarded
    def start_task(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        return self._tasks.start_task(project_id, session_id, window_id, command)

    @guarded
    def get_task(self, project_id: str, session_id: str, window_id: int, task_id: str) -> Json:
        return self._tasks.get_task(project_id, session_id, window_id, task_id)

    @guarded
    def get_call(self, project_id: str, session_id: str, window_id: int, call_id: str) -> Json:
        return self._tasks.get_call(project_id, session_id, window_id, call_id)

    @guarded
    def recover_call(
        self, project_id: str, session_id: str, window_id: int, call_id: str, command: Json
    ) -> Json:
        return self._tasks.recover_call(project_id, session_id, window_id, call_id, command)

    @guarded
    def continue_task(
        self, project_id: str, session_id: str, window_id: int, task_id: str, command: Json
    ) -> Json:
        return self._tasks.continue_task(project_id, session_id, window_id, task_id, command)

    @guarded
    def settle_call(
        self, project_id: str, session_id: str, window_id: int, call_id: str, command: Json
    ) -> Json:
        return self._tasks.settle_call(project_id, session_id, window_id, call_id, command)

    @guarded
    def set_external_expense(
        self, project_id: str, session_id: str, window_id: int, expense_id: str, command: Json
    ) -> Json:
        return self._tasks.set_external_expense(
            project_id, session_id, window_id, expense_id, command
        )

    @guarded
    def get_cost_summary(self, project_id: str, session_id: str, window_id: int) -> Json:
        return self._tasks.get_cost_summary(project_id, session_id, window_id)

    @guarded
    def list_tasks(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Json:
        return self._tasks.list_tasks(project_id, session_id, window_id, cursor, limit)

    @guarded
    def list_cost_entries(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Json:
        return self._tasks.list_cost_entries(project_id, session_id, window_id, cursor, limit)

    @guarded
    def get_task_activity(self) -> list[Json]:
        return self._tasks.get_task_activity()

    @guarded
    def save_draft(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        draft_id: str,
        command: Json,
    ) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        if session.lock is None:
            raise ProjectError("PROJECT_READ_ONLY", 403)
        operation = uuid(command["clientOperationId"])
        draft_id = uuid(draft_id)
        serialized = canonical(command)
        if len(serialized.encode("utf-8")) > 1024 * 1024:
            raise ProjectError("VALIDATION_FAILED", 422)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        with connect(session.directory / DATABASE) as db, db:
            db.execute("BEGIN IMMEDIATE")
            project = self._project_row(db, project_id)
            previous = db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            if previous is not None:
                if (
                    previous["request_hash"] != digest
                    or previous["operation_name"] != "saveDraft"
                    or previous["resource_id"] != draft_id
                ):
                    raise ProjectError("OPERATION_ID_REUSED")
                receipt: Json = json.loads(previous["receipt_json"])
                return receipt
            if set(command) != {"clientOperationId", "expectedRevision", "payload"}:
                raise ProjectError("VALIDATION_FAILED", 422)
            expected = command["expectedRevision"]
            if type(expected) is not int or not 0 <= expected < 9007199254740991:
                raise ProjectError("VALIDATION_FAILED", 422)
            if expected != project["revision"]:
                raise ProjectError("REVISION_CONFLICT")
            payload = command["payload"]
            if (
                set(payload) != {"draftId", "artifactId", "baseRevisionId", "content"}
                or uuid(payload["draftId"]) != draft_id
            ):
                raise ProjectError("VALIDATION_FAILED", 422)
            if payload["baseRevisionId"] is not None:
                from app.storage import revisions

                revisions.get(db, uuid(payload["baseRevisionId"]), uuid(payload["artifactId"]))
            uuid(payload["artifactId"])
            content = drafts.prepare_content(payload["content"])
            saved_at = now()
            drafts.store(db, payload, canonical(content), saved_at)
            revision = expected + 1
            db.execute(
                "UPDATE projects SET revision=?,saved_at=? WHERE id=?",
                (revision, saved_at, project_id),
            )
            receipt = self._receipt(operation, draft_id, revision)
            db.execute(
                """INSERT INTO operations
                   (id,request_hash,operation_name,committed_revision,resource_id,
                    receipt_json,created_at) VALUES (?,?,'saveDraft',?,?,?,?)""",
                (operation, digest, revision, draft_id, canonical(receipt), saved_at),
            )
        return receipt

    @guarded
    def get_draft(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        draft_id: str,
    ) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        draft_id = uuid(draft_id)
        with connect(session.directory / DATABASE, "ro") as db:
            self._project_row(db, project_id)
            return drafts.get(db, draft_id)

    @guarded
    def list_drafts(self, project_id: str, session_id: str, window_id: int) -> list[Json]:
        session = self._draft_session(project_id, session_id, window_id)
        with connect(session.directory / DATABASE, "ro") as db:
            self._project_row(db, project_id)
            return drafts.summaries(db)

    @guarded
    def get_project_operation(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        operation_id: str,
    ) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        operation_id = uuid(operation_id)
        with connect(session.directory / DATABASE, "ro") as db:
            self._project_row(db, project_id)
            row = db.execute(
                "SELECT receipt_json FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        return {
            "operationId": operation_id,
            "state": json.loads(row["receipt_json"])["state"],
            "receipt": json.loads(row["receipt_json"]),
        }

    @guarded
    def close_session(self, session_id: str, window_id: int) -> None:
        if session_id not in self._sessions:
            return
        session = self._session(session_id, window_id)
        if session.lock:
            if self._media.busy(session.directory) or self._tasks.executor.busy(session.directory):
                self._detached_locks[session.directory] = session.lock
            else:
                session.lock.close()
        del self._sessions[session_id]

    @guarded
    def recent_projects(self) -> list[Json]:
        with connect(self._application, "ro") as db:
            return [
                {
                    "projectId": row["project_id"],
                    "name": row["name"],
                    "lastOpenedAt": row["last_opened_at"],
                }
                for row in db.execute(
                    "SELECT * FROM recent_projects ORDER BY last_opened_at DESC LIMIT 50"
                )
            ]

    @guarded
    def recent_project_directory(self, project_id: str) -> Path:
        """Internal main-process lookup; never serialize this result to the renderer."""
        with connect(self._application, "ro") as db:
            row = db.execute(
                "SELECT directory FROM recent_projects WHERE project_id=?", (project_id,)
            ).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        directory = Path(row["directory"])
        project = self._read_project(directory / DATABASE, True)
        if project["id"] != project_id:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        return directory

    @guarded
    def get_global_operation(self, operation_id: str) -> Json:
        operation_id = uuid(operation_id)
        with connect(self._application) as db:
            row = db.execute(
                "SELECT * FROM global_operations WHERE id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        receipt = (
            json.loads(row["receipt_json"]) if row["state"] == "accepted" else self._recover(row)
        )
        return {"operationId": operation_id, "state": receipt["state"], "receipt": receipt}

    def reset(self) -> None:
        with self._mutex:
            for identifier, session in list(self._sessions.items()):
                self.close_session(identifier, session.window_id)
            self._grants.clear()
            self._used_grant_ids.clear()
            self._grant_operations.clear()

    def close(self) -> None:
        self.reset()
        self._settings.clear()
        self._media.shutdown()
        self._tasks.executor.shutdown()

    def _media_finished(self, directory: Path) -> None:
        if not self._media.busy(directory) and not self._tasks.executor.busy(directory):
            lock = self._detached_locks.pop(directory, None)
            if lock:
                lock.close()

    @guarded
    def get_tool_settings(self) -> Json:
        with connect(self._application, "ro") as db:
            row = db.execute("SELECT * FROM settings WHERE singleton=1").fetchone()
        details = self._settings.details()
        provider_ids = {entry["providerId"] for entry in details["credentials"]}
        provider_ids.update(entry["providerId"] for entry in details["storageProfiles"])
        providers = []
        for provider in sorted(provider_ids):
            credential = next(
                (entry for entry in details["credentials"] if entry["providerId"] == provider), None
            )
            providers.append(
                {
                    "providerId": provider,
                    "credentialConfigured": credential is not None,
                    "maskedSuffix": credential["maskedSuffix"] if credential else None,
                    "storageConfigured": any(
                        entry["providerId"] == provider for entry in details["storageProfiles"]
                    ),
                }
            )
        return {
            "revision": row["revision"],
            "providers": providers,
            "ffmpegConfigured": row["ffmpeg_path"] is not None,
            "capabilities": capabilities.list_profiles(self._application),
        }

    @guarded
    def get_settings_details(self) -> Json:
        return self._settings.details()

    @guarded
    def set_credential(self, provider_id: str, command: Json, window_id: int) -> Json:
        return self._settings.set_credential(provider_id, command)

    @guarded
    def delete_credential(self, provider_id: str, command: Json, window_id: int) -> Json:
        return self._settings.delete_credential(provider_id, command)

    @guarded
    def configure_storage(self, command: Json, window_id: int) -> Json:
        return self._settings.configure_storage(command)

    @guarded
    def configure_stage(
        self, project_id: str, session_id: str, window_id: int, command: Json
    ) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        if session.lock is None:
            raise ProjectError("PROJECT_READ_ONLY", 403)
        operation, digest = self._command_identity(command, {"phase", "capabilityId"})
        with connect(session.directory / DATABASE) as db, db:
            db.execute("BEGIN IMMEDIATE")
            project = self._project_row(db, project_id)
            old = db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            if old is not None:
                return self._replay(old, digest, "configureStageModel")
            if project["revision"] != command["expectedRevision"]:
                raise ProjectError("REVISION_CONFLICT")
            profile = capabilities.get(self._application, uuid(command["payload"]["capabilityId"]))
            phase = command["payload"]["phase"]
            if phase not in profile["phases"]:
                raise ProjectError("CAPABILITY_PHASE_MISMATCH", 422)
            db.execute(
                "INSERT INTO stage_models VALUES(?,?,?) ON CONFLICT(phase) DO UPDATE SET "
                "capability_id=excluded.capability_id,capability_version=excluded.capability_version",
                (phase, profile["id"], profile["version"]),
            )
            revision = project["revision"] + 1
            receipt = self._receipt(operation, profile["id"], revision)
            db.execute(
                "UPDATE projects SET revision=?,saved_at=? WHERE id=?",
                (revision, now(), project_id),
            )
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?)",
                (
                    operation,
                    digest,
                    "configureStageModel",
                    revision,
                    profile["id"],
                    canonical(receipt),
                    now(),
                ),
            )
        return receipt

    @guarded
    def get_stage_models(self, project_id: str, session_id: str, window_id: int) -> list[Json]:
        session = self._draft_session(project_id, session_id, window_id)
        with connect(session.directory / DATABASE, "ro") as db:
            db.execute("BEGIN")
            self._project_row(db, project_id)
            if db.execute("PRAGMA user_version").fetchone()[0] == 2:
                return []
            return [
                {
                    "phase": row["phase"],
                    "capabilityId": row["capability_id"],
                    "capabilityVersion": row["capability_version"],
                }
                for row in db.execute("SELECT * FROM stage_models ORDER BY phase")
            ]

    def check_connection(self, command: Json, window_id: int) -> Json:
        receipt, work = self._accept_connection_check(command)
        if work is None:
            return receipt
        profile, secret, credential_id = work
        result = capabilities.run_free_check(self._free_checkers[profile["id"]], profile, secret)
        self._finish_connection_check(receipt["resourceId"], profile, credential_id, result)
        return receipt

    @guarded
    def _accept_connection_check(self, command: Json) -> tuple[Json, tuple[Json, Json, str] | None]:
        operation, digest = settings.identity(command, {"capabilityId"})
        with connect(self._application) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = settings.replay(db, operation, digest, "checkConnection")
            if old is not None:
                return old, None
            revision = settings.cas(db, command)
            identifier = uuid(command["payload"]["capabilityId"])
            if identifier not in self._free_checkers:
                raise ProjectError("CONNECTION_CHECK_UNAVAILABLE", 422)
            profile = capabilities.get(self._application, identifier)
            secret = self._settings.secret(profile["providerId"])
            credential_id = next(
                entry["id"]
                for entry in self._settings.details()["credentials"]
                if entry["providerId"] == profile["providerId"]
            )
            resource = str(uuid4())
            db.execute(
                "INSERT INTO global_jobs VALUES(?,'connection_check','running',NULL)", (resource,)
            )
            receipt = settings.record(
                db, command, digest, "checkConnection", resource, revision, state="accepted"
            )
        return receipt, (profile, secret, credential_id)

    @guarded
    def _finish_connection_check(
        self, job: str, profile: Json, credential_id: str, result: bool | None
    ) -> None:
        current_ids = {entry["id"] for entry in self._settings.details()["credentials"]}
        with connect(self._application) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = "succeeded" if result is not None else "failed"
            result_data = {
                "errorCode": None if result is not None else "CONNECTION_CHECK_FAILED",
                "accountState": "available" if result is True else "unavailable",
            }
            db.execute(
                "UPDATE global_jobs SET state=?,result_json=? WHERE id=?",
                (state, canonical(result_data), job),
            )
            if credential_id in current_ids:
                current = capabilities.get(self._application, profile["id"])
                if current["version"] == profile["version"]:
                    current["accountState"] = result_data["accountState"]
                    current["enabled"] = result is True and current["interfaceState"] == "verified"
                    db.execute(
                        "UPDATE capabilities SET profile_json=?,checked_at=? WHERE id=?",
                        (canonical(current), now(), current["id"]),
                    )

    @guarded
    def get_global_job(self, job_id: str) -> Json:
        with connect(self._application, "ro") as db:
            row = db.execute("SELECT * FROM global_jobs WHERE id=?", (uuid(job_id),)).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        result = json.loads(row["result_json"]) if row["result_json"] else {}
        return {
            "id": row["id"],
            "kind": "connection_check",
            "state": row["state"],
            "progress": 1 if row["state"] == "succeeded" else 0,
            "resultId": None,
            "errorCode": result.get("errorCode"),
        }

    def configure_tools(self, command: Json, window_id: int) -> Json:
        try:
            return self._configure_tools_shared(command, window_id)
        except ProjectError:
            raise
        except (OSError, sqlite3.Error):
            raise ProjectError("STORAGE_UNAVAILABLE", 503) from None
        except (KeyError, TypeError, ValueError):
            raise ProjectError("VALIDATION_FAILED", 422) from None

    def _configure_tools_shared(self, command: Json, window_id: int) -> Json:
        operation, digest = self._command_identity(command, {"ffmpegGrantId"})
        with self._mutex:
            previous = self._tool_operations.get(operation)
            if previous is not None:
                if previous[0] != digest:
                    raise ProjectError("OPERATION_ID_REUSED")
                future = previous[1]
                owner = False
            else:
                future = Future[Json]()
                self._tool_operations[operation] = (digest, future)
                owner = True
        # A retried HTTP request waits without holding the project/draft mutex.
        if not owner:
            return dict(future.result())
        try:
            receipt = self._configure_tools(command, window_id)
        except BaseException as error:
            future.set_exception(error)
            raise
        future.set_result(receipt)
        return dict(receipt)

    def _configure_tools(self, command: Json, window_id: int) -> Json:
        # Probe outside the global mutex, then recheck CAS in the final short transaction.
        with self._mutex:
            operation, digest = self._command_identity(command, {"ffmpegGrantId"})
            with connect(self._application, "ro") as db:
                previous = db.execute(
                    "SELECT * FROM global_operations WHERE id=?", (operation,)
                ).fetchone()
                if previous is not None:
                    return self._replay(previous, digest, "configureMediaTools")
                revision = db.execute("SELECT revision FROM settings").fetchone()[0]
            if command["expectedRevision"] != revision:
                raise ProjectError("REVISION_CONFLICT")
            ffmpeg = self._grant(command["payload"]["ffmpegGrantId"], "ffmpeg", window_id)
        info = tools.inspect_tools(ffmpeg)
        with self._mutex, connect(self._application) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM global_operations WHERE id=?", (operation,)
            ).fetchone()
            if previous is not None:
                return self._replay(previous, digest, "configureMediaTools")
            if db.execute("SELECT revision FROM settings").fetchone()[0] != revision:
                raise ProjectError("REVISION_CONFLICT")
            receipt = self._receipt(operation, str(uuid4()), revision + 1)
            db.execute(
                "UPDATE settings SET revision=?,ffmpeg_path=?,ffmpeg_probe_json=?",
                (revision + 1, str(ffmpeg), canonical(info)),
            )
            db.execute(
                "INSERT INTO global_operations VALUES(?,?,?,?,?,?,?,?)",
                (
                    operation,
                    digest,
                    "configureMediaTools",
                    "committed",
                    receipt["resourceId"],
                    canonical(receipt),
                    "",
                    canonical(command),
                ),
            )
        return receipt

    @staticmethod
    def _command_identity(command: Json, fields: set[str]) -> tuple[str, str]:
        if (
            set(command) != {"clientOperationId", "expectedRevision", "payload"}
            or not isinstance(command["payload"], dict)
            or set(command["payload"]) != fields
            or type(command["expectedRevision"]) is not int
            or not 0 <= command["expectedRevision"] < 9007199254740991
        ):
            raise ProjectError("VALIDATION_FAILED", 422)
        return uuid(command["clientOperationId"]), hashlib.sha256(
            canonical(command).encode()
        ).hexdigest()

    @staticmethod
    def _replay(row: sqlite3.Row, digest: str, name: str, resource: str | None = None) -> Json:
        if (
            row["request_hash"] != digest
            or row["operation_name"] != name
            or (resource is not None and row["resource_id"] != resource)
        ):
            raise ProjectError("OPERATION_ID_REUSED")
        receipt: Json = json.loads(row["receipt_json"])
        return receipt

    @guarded
    def import_media(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        return self._accept_import(project_id, session_id, window_id, command, None)

    @guarded
    def relocate_media(
        self, project_id: str, session_id: str, window_id: int, media_id: str, command: Json
    ) -> Json:
        return self._accept_import(project_id, session_id, window_id, command, uuid(media_id))

    def _accept_import(
        self, project_id: str, session_id: str, window_id: int, command: Json, media_id: str | None
    ) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        if session.lock is None:
            raise ProjectError("PROJECT_READ_ONLY", 403)
        if self._media.stop.is_set():
            raise ProjectError("STORAGE_UNAVAILABLE", 503)
        fields = {"fileGrantId", "expectedHash"} if media_id else {"fileGrantId", "purpose"}
        operation, digest = self._command_identity(command, fields)
        name = "relocateMedia" if media_id else "importMedia"
        with connect(session.directory / DATABASE) as db, db:
            db.execute("BEGIN IMMEDIATE")
            project = self._project_row(db, project_id)
            previous = db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            if previous is not None:
                receipt = self._replay(previous, digest, name)
                if media_id:
                    old_job = db.execute(
                        "SELECT snapshot_json FROM local_jobs WHERE id=?", (receipt["resourceId"],)
                    ).fetchone()
                    if old_job is None or json.loads(old_job[0])["mediaId"] != media_id:
                        raise ProjectError("OPERATION_ID_REUSED")
                return receipt
            if project["revision"] != command["expectedRevision"]:
                raise ProjectError("REVISION_CONFLICT")
            payload = command["payload"]
            if media_id:
                existing = media.media_row(db, media_id)
                if payload["expectedHash"] != existing["sha256"]:
                    raise ProjectError("MEDIA_HASH_MISMATCH")
                if db.execute(
                    "SELECT 1 FROM local_jobs WHERE state IN ('queued','running') "
                    "AND json_extract(snapshot_json,'$.mediaId')=?",
                    (media_id,),
                ).fetchone():
                    raise ProjectError("PROJECT_BUSY")
            elif payload["purpose"] not in {
                "reference",
                "speech",
                "video",
                "music",
                "sfx",
                "evidence",
            }:
                raise ProjectError("VALIDATION_FAILED", 422)
            with connect(self._application, "ro") as app:
                ffmpeg = app.execute("SELECT ffmpeg_path FROM settings").fetchone()[0]
            if ffmpeg is None:
                raise ProjectError("MEDIA_TOOLS_NOT_CONFIGURED", 422)
            source = self._grant(payload["fileGrantId"], "importMedia", window_id)
            if source.suffix.lower() not in tools.EXTENSIONS:
                raise ProjectError("MEDIA_FORMAT_UNSUPPORTED", 422)
            media.require_space(session.directory, source.stat().st_size)
            job_id, intent_id = str(uuid4()), str(uuid4())
            snapshot = {
                "projectId": project_id,
                "sourcePath": str(source),
                "ffmpegPath": ffmpeg,
                "mediaId": media_id or str(uuid4()),
                "relocate": media_id is not None,
                "purpose": payload.get("purpose", "reference"),
                "expectedHash": payload.get("expectedHash"),
            }
            # Relocation publishes to a fresh path; existing/corrupt originals are preserved.
            staging = ".media-staging/" + job_id + source.suffix.lower()
            target = "media/" + job_id + source.suffix.lower()
            revision = project["revision"] + 1
            receipt = self._receipt(operation, job_id, revision)
            receipt["state"] = "accepted"
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?)",
                (operation, digest, name, revision, job_id, canonical(receipt), now()),
            )
            if media_id:
                # A media has one intent. Its previous operation/receipt/job remain immutable.
                db.execute("DELETE FROM import_intents WHERE media_id=?", (media_id,))
            db.execute(
                "INSERT INTO import_intents VALUES(?,?,?,?,?,?,?,?)",
                (
                    intent_id,
                    snapshot["mediaId"],
                    "local",
                    payload.get("expectedHash"),
                    staging,
                    target,
                    "planned",
                    operation,
                ),
            )
            db.execute(
                "INSERT INTO local_jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (job_id, "import", "queued", 1, 0, canonical(snapshot), None, None, operation),
            )
            db.execute(
                "UPDATE projects SET revision=?,saved_at=? WHERE id=?",
                (revision, now(), project_id),
            )
        self._media.enqueue(session.directory, job_id, project_id)
        return receipt

    @guarded
    def get_job(self, project_id: str, session_id: str, window_id: int, job_id: str) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        with connect(session.directory / DATABASE, "ro") as db:
            db.execute("BEGIN")
            self._project_row(db, project_id)
            row = db.execute("SELECT * FROM local_jobs WHERE id=?", (uuid(job_id),)).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        return {
            "id": row["id"],
            "kind": row["kind"],
            "state": row["state"],
            "progress": 1 if row["state"] == "succeeded" else 0,
            "resultId": row["result_id"],
            "errorCode": row["error_code"],
        }

    @guarded
    def list_jobs(self, project_id: str, session_id: str, window_id: int) -> list[Json]:
        session = self._draft_session(project_id, session_id, window_id)
        with connect(session.directory / DATABASE, "ro") as db:
            db.execute("BEGIN")
            self._project_row(db, project_id)
            rows = db.execute("SELECT id FROM local_jobs ORDER BY rowid DESC LIMIT 50").fetchall()
        return [self.get_job(project_id, session_id, window_id, row[0]) for row in rows]

    @guarded
    def cancel_job(
        self, project_id: str, session_id: str, window_id: int, job_id: str, command: Json
    ) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        if session.lock is None:
            raise ProjectError("PROJECT_READ_ONLY", 403)
        job_id = uuid(job_id)
        operation, digest = self._command_identity(command, {"reason"})
        with connect(session.directory / DATABASE) as db, db:
            db.execute("BEGIN IMMEDIATE")
            project = self._project_row(db, project_id)
            previous = db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            if previous is not None:
                return self._replay(previous, digest, "cancelJob", job_id)
            if project["revision"] != command["expectedRevision"]:
                raise ProjectError("REVISION_CONFLICT")
            reason = command["payload"]["reason"]
            if not isinstance(reason, str) or not 1 <= len(reason) <= 500:
                raise ProjectError("VALIDATION_FAILED", 422)
            job = db.execute("SELECT * FROM local_jobs WHERE id=?", (job_id,)).fetchone()
            if job is None:
                raise ProjectError("OBJECT_NOT_FOUND", 404)
            if job["state"] not in {"queued", "running", "cancelled"}:
                raise ProjectError("JOB_NOT_CANCELLABLE")
            revision = project["revision"] + 1
            receipt = self._receipt(operation, job_id, revision)
            db.execute(
                "UPDATE local_jobs SET state='cancelled',active=0,error_code=NULL WHERE id=?",
                (job_id,),
            )
            db.execute(
                "UPDATE import_intents SET state='quarantined' WHERE operation_id=?",
                (job["operation_id"],),
            )
            db.execute(
                "UPDATE projects SET revision=?,saved_at=? WHERE id=?",
                (revision, now(), project_id),
            )
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?)",
                (operation, digest, "cancelJob", revision, job_id, canonical(receipt), now()),
            )
        self._media.cancel(session.directory, job_id)
        return receipt

    @guarded
    def get_media(self, project_id: str, session_id: str, window_id: int, media_id: str) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        with connect(session.directory / DATABASE, "ro") as db:
            db.execute("BEGIN")
            self._project_row(db, project_id)
            return media.dto(session.directory, media.media_row(db, uuid(media_id)))

    @guarded
    def list_media(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Json:
        session = self._draft_session(project_id, session_id, window_id)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ProjectError("VALIDATION_FAILED", 422)
        after = uuid(cursor) if cursor is not None else ""
        with connect(session.directory / DATABASE, "ro") as db:
            db.execute("BEGIN")
            self._project_row(db, project_id)
            rows = db.execute(
                "SELECT * FROM media_files WHERE id>? ORDER BY id LIMIT ?", (after, limit + 1)
            ).fetchall()
        return {
            "items": [media.dto(session.directory, row) for row in rows[:limit]],
            "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

    @guarded
    def media_file(self, project_id: str, session_id: str, window_id: int, media_id: str) -> Path:
        session = self._draft_session(project_id, session_id, window_id)
        with connect(session.directory / DATABASE, "ro") as db:
            db.execute("BEGIN")
            self._project_row(db, project_id)
            row = media.media_row(db, uuid(media_id))
        if media.dto(session.directory, row)["availability"] != "available":
            raise ProjectError("MEDIA_MISSING", 404)
        return relative_file(session.directory, row["relative_path"])

    def backup_project(self, project_id: str, session_id: str, window_id: int) -> Path:
        with self._mutex:
            session = self._draft_session(project_id, session_id, window_id)
            directory = session.directory
        return backup_project_database(directory, project_id)

    @guarded
    def get_artifact(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str
    ) -> Json:
        return self._versions.get_artifact(project_id, session_id, window_id, artifact_id)

    @guarded
    def list_revisions(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        artifact_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Json:
        return self._versions.list_revisions(
            project_id, session_id, window_id, artifact_id, cursor=cursor, limit=limit
        )

    @guarded
    def create_revision(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, command: Json
    ) -> Json:
        return self._versions.create_revision(
            project_id, session_id, window_id, artifact_id, command
        )

    @guarded
    def preview_adoption(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, payload: Json
    ) -> Json:
        return self._versions.preview_adoption(
            project_id, session_id, window_id, artifact_id, payload
        )

    @guarded
    def adopt_revision(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, command: Json
    ) -> Json:
        return self._versions.adopt_revision(
            project_id, session_id, window_id, artifact_id, command
        )

    @guarded
    def confirm_revision(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, command: Json
    ) -> Json:
        return self._versions.confirm_revision(
            project_id, session_id, window_id, artifact_id, command
        )

    @guarded
    def undo_adoption(
        self, project_id: str, session_id: str, window_id: int, adoption_id: str, command: Json
    ) -> Json:
        return self._versions.undo_adoption(project_id, session_id, window_id, adoption_id, command)

    @guarded
    def run_local_checks(
        self, project_id: str, session_id: str, window_id: int, command: Json
    ) -> Json:
        return self._versions.run_local_checks(project_id, session_id, window_id, command)

    @guarded
    def get_check_report(
        self, project_id: str, session_id: str, window_id: int, check_id: str
    ) -> Json:
        return self._versions.get_check_report(project_id, session_id, window_id, check_id)
