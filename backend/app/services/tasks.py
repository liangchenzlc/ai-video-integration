"""Project-scoped commands, transaction receipts and reads for T04."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.projects import ProjectService, Session

from app.services.task_adapter import SyntheticAdapter
from app.services.task_executor import TaskExecutor
from app.storage import candidates, costs, task_plans, tasks
from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.settings import canonical

Json = dict[str, Any]


class TaskService:
    def __init__(self, owner: "ProjectService", adapter: Any = None) -> None:
        self.owner = owner
        self.adapter = adapter or SyntheticAdapter()
        self.executor = TaskExecutor(self)
        self.known_projects: dict[Path, str] = {}

    def write(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        command: Json,
        name: str,
        fields: set[str],
        action: Callable[[sqlite3.Connection, sqlite3.Row, Json, "Session"], str],
        resource: str | None = None,
    ) -> Json:
        from app.services.projects import now

        session = self.owner._draft_session(project_id, session_id, window_id)
        if session.lock is None:
            raise ProjectError("PROJECT_READ_ONLY", 403)
        operation, digest = self.owner._command_identity(command, fields)
        with connect(session.directory / "project.sqlite3") as db, db:
            db.execute("BEGIN IMMEDIATE")
            project = self.owner._project_row(db, project_id)
            previous = db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            if previous is not None:
                return self.owner._replay(previous, digest, name, resource)
            if command["expectedRevision"] != project["revision"]:
                raise ProjectError("REVISION_CONFLICT")
            resource_id = action(db, project, command["payload"], session)
            revision = project["revision"] + 1
            receipt = self.owner._receipt(operation, resource_id, revision)
            if name in {"startTask", "recoverCall", "continueTask"}:
                receipt["state"] = "accepted"
            db.execute(
                "UPDATE projects SET revision=?,saved_at=? WHERE id=?",
                (revision, now(), project_id),
            )
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?)",
                (operation, digest, name, revision, resource_id, canonical(receipt), now()),
            )
        return receipt

    def read(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        action: Callable[[sqlite3.Connection, sqlite3.Row], Json],
    ) -> Json:
        session = self.owner._draft_session(project_id, session_id, window_id)
        with connect(session.directory / "project.sqlite3", "ro") as db:
            project = self.owner._project_row(db, project_id)
            return action(db, project)

    def get_budget(self, project_id: str, session_id: str, window_id: int) -> Json:
        return self.read(project_id, session_id, window_id, costs.budget)

    def set_budget(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        def action(
            db: sqlite3.Connection, project: sqlite3.Row, payload: Json, session: "Session"
        ) -> str:
            costs.set_budget(db, project, payload)
            return project_id

        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "setBudget",
            {"totalMicroCny", "allocations", "warningPercent"},
            action,
            project_id,
        )

    def plan_task(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        def action(
            db: sqlite3.Connection, project: sqlite3.Row, payload: Json, session: "Session"
        ) -> str:
            return str(task_plans.compile_plan(db, project, payload, self.adapter)["id"])

        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "planTask",
            {
                "objectId",
                "stage",
                "phase",
                "goal",
                "inputRevisionIds",
                "candidates",
                "includePrecheck",
                "executionMode",
            },
            action,
        )

    def get_task_plan(self, project_id: str, session_id: str, window_id: int, plan_id: str) -> Json:
        return self.read(
            project_id, session_id, window_id, lambda db, _: task_plans.get(db, plan_id)
        )

    def start_task(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        from uuid import uuid4

        accepted = []

        def action(
            db: sqlite3.Connection, project: sqlite3.Row, payload: Json, session: "Session"
        ) -> str:
            plan = task_plans.get(db, payload["planId"])
            task_plans.validate_current(db, plan, self.adapter)
            if (
                payload["disclosureAccepted"] is not True
                or task_plans.amount(payload["authorizedMaximumMicroCny"])
                != plan["maximumMicroCny"]
            ):
                raise ProjectError("VALIDATION_FAILED", 422)
            if (
                self.executor.busy()
                or self.executor.stop.is_set()
                or db.execute("SELECT 1 FROM user_tasks WHERE plan_id=?", (plan["id"],)).fetchone()
            ):
                raise ProjectError("TASK_BUSY")
            costs.check_limits(db, project, plan["stage"], plan["maximumMicroCny"])
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO "
                "user_tasks(id,plan_id,state,active,authorized_maximum_micro_cny) "
                "VALUES(?,?,'pending',1,?)",
                (identifier, plan["id"], plan["maximumMicroCny"]),
            )
            for revision_id in plan["inputRevisionIds"]:
                db.execute("INSERT INTO task_inputs VALUES(?,?)", (identifier, revision_id))
            tasks.prepare_next(db, project, identifier, self.adapter)
            accepted.append((session.directory, project_id, identifier))
            return identifier

        receipt = self.write(
            project_id,
            session_id,
            window_id,
            command,
            "startTask",
            {"planId", "authorizedMaximumMicroCny", "disclosureAccepted"},
            action,
        )
        if accepted:
            self.executor.enqueue(*accepted[0])
        return receipt

    def get_task(self, project_id: str, session_id: str, window_id: int, task_id: str) -> Json:
        return self.read(project_id, session_id, window_id, lambda db, _: tasks.task(db, task_id))

    def list_task_candidates(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        task_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Json:
        return self.read(
            project_id,
            session_id,
            window_id,
            lambda db, _: candidates.page(db, task_id, cursor, limit),
        )

    def get_call(self, project_id: str, session_id: str, window_id: int, call_id: str) -> Json:
        return self.read(project_id, session_id, window_id, lambda db, _: tasks.call(db, call_id))

    def list_tasks(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Json:
        return self.read(
            project_id, session_id, window_id, lambda db, _: tasks.summaries(db, cursor, limit)
        )

    def recover_call(
        self, project_id: str, session_id: str, window_id: int, call_id: str, command: Json
    ) -> Json:
        accepted = []

        def action(
            db: sqlite3.Connection, project: sqlite3.Row, payload: Json, session: "Session"
        ) -> str:
            call = tasks.call(db, call_id)
            action_name = payload["action"]
            if action_name == "stop_waiting":
                db.execute(
                    "UPDATE user_tasks SET observation_stopped=1 WHERE id=?", (call["taskId"],)
                )
                tasks.event(db, call_id, "observation_stopped", {})
                return call_id
            if action_name not in {"query", "download"}:
                raise ProjectError("RECOVERY_NOT_ALLOWED")
            if self.executor.busy() or self.executor.stop.is_set():
                raise ProjectError("TASK_BUSY")
            row = db.execute(
                "SELECT result_json FROM service_calls WHERE id=?", (call_id,)
            ).fetchone()
            if action_name == "query" and (
                not call["remoteTaskId"]
                or row["result_json"] is not None
                or call["state"] not in {"running", "result_unknown"}
            ):
                raise ProjectError("RECOVERY_NOT_ALLOWED")
            if action_name == "download" and (
                row["result_json"] is None or call["state"] != "pending_download"
            ):
                raise ProjectError("RECOVERY_NOT_ALLOWED")
            db.execute(
                "UPDATE user_tasks SET active=1,state='pending',observation_stopped=0 WHERE id=?",
                (call["taskId"],),
            )
            accepted.append((session.directory, project_id, call["taskId"], action_name, call_id))
            return call_id

        receipt = self.write(
            project_id, session_id, window_id, command, "recoverCall", {"action"}, action, call_id
        )
        if accepted:
            self.executor.enqueue(*accepted[0])
        return receipt

    def continue_task(
        self, project_id: str, session_id: str, window_id: int, task_id: str, command: Json
    ) -> Json:
        accepted = []

        def action(
            db: sqlite3.Connection, project: sqlite3.Row, payload: Json, session: "Session"
        ) -> str:
            task = tasks.task(db, task_id)
            if payload["confirmedUnsubmittedOnly"] is not True:
                raise ProjectError("VALIDATION_FAILED", 422)
            if self.executor.busy() or self.executor.stop.is_set():
                raise ProjectError("TASK_BUSY")
            states = [
                r[0]
                for r in db.execute("SELECT state FROM service_calls WHERE task_id=?", (task_id,))
            ]
            if task["state"] == "complete" or any(
                state not in {"prepared", "succeeded"} for state in states
            ):
                raise ProjectError("RECOVERY_NOT_ALLOWED")
            plan = task_plans.get(db, task["planId"])
            task_plans.validate_current(db, plan, self.adapter, expiry=False)
            db.execute(
                "UPDATE user_tasks SET active=1,state='pending',observation_stopped=0 WHERE id=?",
                (task_id,),
            )
            accepted.append((session.directory, project_id, task_id))
            return task_id

        receipt = self.write(
            project_id,
            session_id,
            window_id,
            command,
            "continueTask",
            {"confirmedUnsubmittedOnly"},
            action,
            task_id,
        )
        if accepted:
            self.executor.enqueue(*accepted[0])
        return receipt

    def settle_call(
        self, project_id: str, session_id: str, window_id: int, call_id: str, command: Json
    ) -> Json:
        def action(
            db: sqlite3.Connection, project: sqlite3.Row, payload: Json, session: "Session"
        ) -> str:
            if tasks.call(db, call_id)["state"] == "prepared":
                raise ProjectError("RECOVERY_NOT_ALLOWED")
            value = task_plans.amount(payload["settledMicroCny"])
            if any(
                not isinstance(payload[key], str) or not payload[key].strip()
                for key in ("basis", "reason")
            ):
                raise ProjectError("VALIDATION_FAILED", 422)
            for media_id in payload["evidenceMediaIds"]:
                if (
                    db.execute(
                        "SELECT 1 FROM media_files WHERE id=?", (task_plans.identifier(media_id),)
                    ).fetchone()
                    is None
                ):
                    raise ProjectError("OBJECT_NOT_FOUND", 404)
            db.execute(
                "UPDATE cost_entries SET state='settled',settled_micro_cny=?,basis=? WHERE "
                "call_id=?",
                (value, payload["basis"], call_id),
            )
            tasks.event(db, call_id, "settlement", payload)
            return call_id

        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "settleCall",
            {"settledMicroCny", "basis", "evidenceMediaIds", "reason"},
            action,
            call_id,
        )

    def set_external_expense(
        self, project_id: str, session_id: str, window_id: int, expense_id: str, command: Json
    ) -> Json:
        def action(
            db: sqlite3.Connection, project: sqlite3.Row, payload: Json, session: "Session"
        ) -> str:
            if (
                task_plans.identifier(payload["expenseId"]) != task_plans.identifier(expense_id)
                or payload["category"] not in {"storage", "transfer", "procurement"}
                or payload["state"] not in {"estimated", "pending", "settled"}
                or not isinstance(payload["basis"], str)
                or not payload["basis"].strip()
            ):
                raise ProjectError("VALIDATION_FAILED", 422)
            value = task_plans.amount(payload["amountMicroCny"])
            db.execute(
                "INSERT INTO external_expenses VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE "
                "SET "
                "category=excluded.category,state=excluded.state,amount_micro_cny=excluded.amount_micro_cny,basis=excluded.basis",
                (expense_id, payload["category"], payload["state"], value, payload["basis"]),
            )
            return expense_id

        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "setExternalExpense",
            {"expenseId", "category", "state", "amountMicroCny", "basis"},
            action,
            expense_id,
        )

    def get_cost_summary(self, project_id: str, session_id: str, window_id: int) -> Json:
        return self.read(project_id, session_id, window_id, costs.summary)

    def list_cost_entries(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Json:
        return self.read(
            project_id, session_id, window_id, lambda db, _: costs.entries(db, cursor, limit)
        )

    def get_task_activity(self) -> list[Json]:
        from app.storage.database import connect

        result = []
        projects = dict(self.known_projects)
        projects.update({s.directory: s.project_id for s in self.owner._sessions.values()})
        if self.executor.active:
            directory, project_id, _ = self.executor.active
            projects[directory] = project_id
        for directory, project_id in projects.items():
            try:
                with connect(directory / "project.sqlite3", "ro") as db:
                    project = self.owner._project_row(db, project_id)
                    if db.execute("PRAGMA user_version").fetchone()[0] < 4:
                        continue
                    entries = [
                        {
                            "projectId": project_id,
                            "projectName": project["name"],
                            "taskId": row["id"],
                            "state": row["state"],
                        }
                        for row in db.execute(
                            "SELECT id,state FROM user_tasks WHERE active=1 OR state IN "
                            "('result_unknown','pending_download','partial','pending')"
                        )
                    ]
                result.extend(entries)
            except (ProjectError, OSError, sqlite3.Error):
                # A retained directory may have moved or been replaced after its session closed.
                # Never leak the replacement's identity or hide other projects' pending work.
                continue
        return result

    def remember_project(self, directory: Path, project_id: str) -> None:
        for previous, identifier in list(self.known_projects.items()):
            if identifier == project_id and previous != directory:
                del self.known_projects[previous]
        self.known_projects[directory] = project_id
