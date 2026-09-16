"""One application execution slot; durable boundaries precede every external action."""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.services import generated_media
from app.storage import candidates, costs, task_plans, tasks
from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.settings import canonical


class TaskExecutor:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.owner = service.owner
        self.active: tuple[Path, str, str] | None = None
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()

    def busy(self, directory: Path | None = None) -> bool:
        return self.active is not None and (directory is None or self.active[0] == directory)

    def enqueue(
        self,
        directory: Path,
        project_id: str,
        task_id: str,
        action: str = "submit",
        call_id: str | None = None,
    ) -> None:
        if self.active is not None or self.stop.is_set():
            raise ProjectError("TASK_BUSY")
        self.active = directory, project_id, task_id
        self.thread = threading.Thread(
            target=self._run,
            args=(directory, project_id, task_id, action, call_id),
            daemon=True,
            name="task-executor",
        )
        self.thread.start()

    def recover(self, directory: Path, project_id: str) -> None:
        if self.busy(directory):
            return
        with connect(directory / "project.sqlite3") as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.owner._project_row(db, project_id)
            self.service.remember_project(directory, project_id)
            for row in db.execute(
                "SELECT * FROM service_calls WHERE state='submitting'"
            ).fetchall():
                state = (
                    "pending_download"
                    if row["result_json"]
                    else "running"
                    if row["remote_task_id"]
                    else "result_unknown"
                )
                db.execute("UPDATE service_calls SET state=? WHERE id=?", (state, row["id"]))
                tasks.event(db, row["id"], "restart_recovery", {"state": state})
            for row in db.execute("SELECT * FROM user_tasks WHERE active=1").fetchall():
                states = [
                    r[0]
                    for r in db.execute(
                        "SELECT state FROM service_calls WHERE task_id=?", (row["id"],)
                    )
                ]
                state = (
                    "result_unknown"
                    if "result_unknown" in states
                    else "pending_download"
                    if "pending_download" in states
                    else "pending"
                )
                tasks.task_event(db, row["id"], state)

    def _run(
        self, directory: Path, project_id: str, task_id: str, action: str, call_id: str | None
    ) -> None:
        adapter = self.service.adapter
        try:
            while not self.stop.is_set():
                with self.owner._mutex, connect(directory / "project.sqlite3") as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    project = self.owner._project_row(db, project_id)
                    row = (
                        db.execute("SELECT * FROM service_calls WHERE id=?", (call_id,)).fetchone()
                        if call_id
                        else db.execute(
                            "SELECT * FROM service_calls WHERE task_id=? AND "
                            "state='prepared' ORDER BY rowid LIMIT 1",
                            (task_id,),
                        ).fetchone()
                    )
                    if row is None:
                        next_id = tasks.prepare_next(db, project, task_id, adapter)
                        if next_id is None:
                            tasks.task_event(db, task_id, "complete")
                            return
                        # Commit prepared before the separate submitting transaction.
                        call_id = next_id
                        continue
                    call_id = row["id"]
                    snapshot = json.loads(row["request_snapshot_json"])
                    if action == "submit":
                        if row["state"] != "prepared":
                            return
                        task = db.execute(
                            "SELECT * FROM user_tasks WHERE id=?", (task_id,)
                        ).fetchone()
                        plan = task_plans.get(db, task["plan_id"])
                        task_plans.validate_current(db, plan, adapter, expiry=False)
                        costs.check_limits(
                            db,
                            project,
                            plan["stage"],
                            0,
                            task_id,
                            task["authorized_maximum_micro_cny"],
                        )
                        db.execute(
                            "UPDATE service_calls SET state='submitting' WHERE id=?", (call_id,)
                        )
                        tasks.event(db, call_id, "submitting", {})
                    tasks.task_event(db, task_id, "running", True)
                # Network / adapter work must never hold the project/draft mutex.
                try:
                    if action == "submit":
                        response = adapter.submit(
                            adapter.prepare(snapshot), row["submission_token"]
                        )
                    elif action == "query":
                        response = adapter.query(row["remote_task_id"], snapshot)
                    else:
                        response = {"result": json.loads(row["result_json"])}
                except Exception:
                    self._failure(
                        directory,
                        project_id,
                        task_id,
                        call_id,
                        "result_unknown",
                        "CALL_RESULT_UNKNOWN",
                    )
                    return
                with self.owner._mutex, connect(directory / "project.sqlite3") as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    self.owner._project_row(db, project_id)
                    if response.get("failed"):
                        self._fail_in(db, task_id, call_id, "failed", "CALL_FAILED")
                        return
                    result = response.get("result")
                    remote = response.get("remoteTaskId") or row["remote_task_id"]
                    state = (
                        "pending_download"
                        if result is not None
                        else "running"
                        if remote
                        else "result_unknown"
                    )
                    db.execute(
                        "UPDATE service_calls SET "
                        "remote_task_id=?,result_json=?,state=?,error_code=NULL WHERE id=?",
                        (remote, canonical(result) if result is not None else None, state, call_id),
                    )
                    tasks.event(db, call_id, "response", {"state": state, "remoteTaskId": remote})
                    if (
                        snapshot["step"]["purpose"] == "create"
                        and snapshot.get("resultProtocolVersion") == "candidate-v1"
                        and result is not None
                    ):
                        candidates.retain_raw(db, call_id, 0, result)
                    if isinstance(result, dict) and result.get("resultType") == "image":
                        try:
                            candidates.validate_image_envelope(result, snapshot)
                        except ProjectError:
                            if (
                                snapshot["step"]["purpose"] == "create"
                                and snapshot.get("resultProtocolVersion") == "candidate-v1"
                            ):
                                candidates.invalidate(db, call_id, 0, "image")
                            self._fail_in(
                                db,
                                task_id,
                                call_id,
                                "failed",
                                candidates.INVALID_RESULT,
                            )
                            return
                    if result is None:
                        tasks.task_event(db, task_id, "result_unknown")
                        return
                try:
                    media_record = None
                    if isinstance(result, dict) and result.get("resultType") == "image":
                        with connect(self.owner._application, "ro") as application:
                            ffmpeg = application.execute(
                                "SELECT ffmpeg_path FROM settings WHERE singleton=1"
                            ).fetchone()[0]
                        if ffmpeg is None:
                            raise ProjectError("MEDIA_TOOLS_NOT_CONFIGURED", 422)
                        media_record = generated_media.publish_image(
                            directory,
                            call_id,
                            0,
                            Path(ffmpeg),
                            self.stop,
                            synthetic=result.get("synthetic") is True,
                            url=result.get("resultRef"),
                        )
                        downloaded = result
                    else:
                        downloaded = adapter.download(result)
                except ProjectError as error:
                    self._failure(
                        directory,
                        project_id,
                        task_id,
                        call_id,
                        "pending_download",
                        error.code,
                    )
                    return
                except Exception:
                    self._failure(
                        directory,
                        project_id,
                        task_id,
                        call_id,
                        "pending_download",
                        "DOWNLOAD_FAILED",
                    )
                    return
                with self.owner._mutex, connect(directory / "project.sqlite3") as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    self.owner._project_row(db, project_id)
                    if (
                        snapshot["step"]["purpose"] == "create"
                        and snapshot.get("resultProtocolVersion") == "candidate-v1"
                    ):
                        try:
                            if (
                                isinstance(downloaded, dict)
                                and downloaded.get("resultType") == "image"
                            ):
                                assert media_record is not None
                                media_id = generated_media.register(db, media_record)
                                candidates.register_image_result(
                                    db,
                                    call_id,
                                    0,
                                    downloaded,
                                    media_id,
                                    media_record["sha256"],
                                )
                            else:
                                candidates.register_text_result(db, call_id, 0, downloaded)
                        except ProjectError:
                            self._fail_in(
                                db,
                                task_id,
                                call_id,
                                "failed",
                                candidates.INVALID_RESULT,
                            )
                            return
                    db.execute(
                        "UPDATE service_calls SET state='succeeded',error_code=NULL WHERE id=?",
                        (call_id,),
                    )
                    tasks.event(db, call_id, "succeeded", {"provenance": "synthetic"})
                    if action != "submit":
                        count = db.execute(
                            "SELECT count(*) FROM service_calls WHERE task_id=? AND "
                            "state!='succeeded'",
                            (task_id,),
                        ).fetchone()[0]
                        plan = task_plans.get(
                            db,
                            db.execute(
                                "SELECT plan_id FROM user_tasks WHERE id=?", (task_id,)
                            ).fetchone()[0],
                        )
                        total = db.execute(
                            "SELECT count(*) FROM service_calls WHERE task_id=?", (task_id,)
                        ).fetchone()[0]
                        complete = not count and total == sum(s["maxCalls"] for s in plan["steps"])
                        tasks.task_event(db, task_id, "complete" if complete else "partial")
                        return
                call_id = None
        except (ProjectError, OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            try:
                with self.owner._mutex, connect(directory / "project.sqlite3") as db, db:
                    self.owner._project_row(db, project_id)
                    tasks.task_event(db, task_id, "partial")
            except (ProjectError, OSError, sqlite3.Error):
                pass  # Durable submitting/prepared boundary is recovered on the next open.
        finally:
            with self.owner._mutex:
                self.active = None
                self.owner._media_finished(directory)

    def _fail_in(
        self, db: sqlite3.Connection, task_id: str, call_id: str, state: str, code: str
    ) -> None:
        db.execute(
            "UPDATE service_calls SET state=?,error_code=? WHERE id=?", (state, code, call_id)
        )
        tasks.event(db, call_id, state, {"errorCode": code})
        success = db.execute(
            "SELECT 1 FROM service_calls WHERE task_id=? AND state='succeeded'", (task_id,)
        ).fetchone()
        tasks.task_event(db, task_id, "partial" if success else state)

    def _failure(
        self, directory: Path, project_id: str, task_id: str, call_id: str, state: str, code: str
    ) -> None:
        with self.owner._mutex, connect(directory / "project.sqlite3") as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.owner._project_row(db, project_id)
            self._fail_in(db, task_id, call_id, state, code)

    def shutdown(self) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
