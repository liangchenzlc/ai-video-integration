"""Short project transactions for immutable candidates, previews and adoption."""

import hashlib
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.storage import adoptions, checks, revisions
from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.settings import canonical
from app.storage.task_plans import identifier

if TYPE_CHECKING:
    from app.services.projects import ProjectService

Json = dict[str, Any]


class VersionService:
    def __init__(self, owner: "ProjectService") -> None:
        self.owner = owner
        self.previews: dict[str, Json] = {}

    def read(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        action: Callable[[sqlite3.Connection, sqlite3.Row], Json],
    ) -> Json:
        session = self.owner._draft_session(project_id, session_id, window_id)
        with connect(session.directory / "project.sqlite3", "ro") as db:
            db.execute("BEGIN")
            project = self.owner._project_row(db, project_id)
            if db.execute("PRAGMA user_version").fetchone()[0] < 5:
                raise ProjectError("PROJECT_VERSION_UNSUPPORTED")
            return action(db, project)

    def write(
        self,
        project_id: str,
        session_id: str,
        window_id: int,
        command: Json,
        name: str,
        fields: set[str],
        route_id: str | None,
        action: Callable[[sqlite3.Connection, sqlite3.Row, Json], str],
    ) -> Json:
        from app.services.projects import now

        session = self.owner._draft_session(project_id, session_id, window_id)
        if session.lock is None:
            raise ProjectError("PROJECT_READ_ONLY", 403)
        operation, _ = self.owner._command_identity(command, fields)
        if route_id is not None:
            identifier(route_id)
        digest = hashlib.sha256(
            canonical({"command": command, "routeId": route_id}).encode("utf-8")
        ).hexdigest()
        with connect(session.directory / "project.sqlite3") as db, db:
            db.execute("BEGIN IMMEDIATE")
            project = self.owner._project_row(db, project_id)
            previous = db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            if previous is not None:
                return self.owner._replay(previous, digest, name)
            if command["expectedRevision"] != project["revision"]:
                raise ProjectError("REVISION_CONFLICT")
            resource_id = action(db, project, command["payload"])
            revision = project["revision"] + 1
            receipt = self.owner._receipt(operation, resource_id, revision)
            if name in {"runLocalChecks", "renderAnimatic", "exportFilm"}:
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

    def get_artifact(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str
    ) -> Json:
        return self.read(
            project_id, session_id, window_id, lambda db, _: revisions.artifact(db, artifact_id)
        )

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
        return self.read(
            project_id,
            session_id,
            window_id,
            lambda db, _: revisions.page(db, artifact_id, cursor, limit),
        )

    def create_revision(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, command: Json
    ) -> Json:
        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "createRevision",
            {"draftId"},
            artifact_id,
            lambda db, _, payload: revisions.create(db, artifact_id, payload["draftId"]),
        )

    def preview_adoption(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, payload: Json
    ) -> Json:
        if (
            set(payload) != {"toRevisionId", "expectedRevision"}
            or type(payload["expectedRevision"]) is not int
        ):
            raise ProjectError("VALIDATION_FAILED", 422)

        def action(db: sqlite3.Connection, project: sqlite3.Row) -> Json:
            if project["revision"] != payload["expectedRevision"]:
                raise ProjectError("REVISION_CONFLICT")
            impact = adoptions.impact(db, artifact_id, payload["toRevisionId"])
            preview_id = str(uuid4())
            impact.update(
                previewId=preview_id,
                expiresAt=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            )
            self.previews = {
                key: value
                for key, value in self.previews.items()
                if value["expires"] > time.monotonic()
            }
            self.previews[preview_id] = {
                "projectId": project_id,
                "sessionId": session_id,
                "windowId": window_id,
                "projectRevision": project["revision"],
                "expires": time.monotonic() + 300,
                "contentHash": revisions.get(db, payload["toRevisionId"])["contentHash"],
                "impact": dict(impact),
            }
            return impact

        return self.read(project_id, session_id, window_id, action)

    def adopt_revision(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, command: Json
    ) -> Json:
        def action(db: sqlite3.Connection, project: sqlite3.Row, payload: Json) -> str:
            if type(payload["confirm"]) is not bool:
                raise ProjectError("VALIDATION_FAILED", 422)
            preview = self.previews.get(identifier(payload["previewId"]))
            if (
                preview is None
                or preview["expires"] <= time.monotonic()
                or preview["projectId"] != project_id
                or preview["sessionId"] != session_id
                or preview["windowId"] != window_id
                or preview["projectRevision"] != project["revision"]
                or preview["impact"]["artifactId"] != artifact_id
                or preview["impact"]["toRevisionId"] != payload["toRevisionId"]
            ):
                raise ProjectError("PREVIEW_STALE")
            target = revisions.get(db, payload["toRevisionId"], artifact_id)
            if target["contentHash"] != preview["contentHash"]:
                raise ProjectError("PREVIEW_STALE")
            revisions.validate_payload(target["payload"])
            revisions.validate_references(db, target["payload"], target["id"])
            impact = adoptions.impact(db, artifact_id, target["id"])
            if any(impact[key] != preview["impact"][key] for key in impact):
                raise ProjectError("PREVIEW_STALE")
            affected = [artifact_id] + impact["affectedArtifactIds"]
            adoptions.check_locks(db, affected)
            before = adoptions.snapshot(db, affected)
            if payload["confirm"]:
                checks.require_coverage(db, target["id"])
            db.execute(
                "UPDATE artifacts SET adopted_revision_id=?,needs_update=? WHERE id=?",
                (target["id"], int(revisions.stale_inputs(db, target["id"])), artifact_id),
            )
            for downstream in impact["affectedArtifactIds"]:
                db.execute("UPDATE artifacts SET needs_update=1 WHERE id=?", (downstream,))
            if payload["confirm"]:
                db.execute(
                    "UPDATE artifacts SET confirmed_revision_id=? WHERE id=?",
                    (target["id"], artifact_id),
                )
            adoption_id = str(uuid4())
            db.execute(
                "INSERT INTO "
                "adoptions(id,artifact_id,from_revision_id,to_revision_id,"
                "before_snapshot_json,undone,operation_id,after_snapshot_json) "
                "VALUES(?,?,?,?,?,0,?,?)",
                (
                    adoption_id,
                    artifact_id,
                    impact["fromRevisionId"],
                    target["id"],
                    canonical(before),
                    command["clientOperationId"],
                    canonical(adoptions.snapshot(db, affected)),
                ),
            )
            return adoption_id

        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "adoptRevision",
            {"previewId", "toRevisionId", "confirm"},
            artifact_id,
            action,
        )

    def confirm_revision(
        self, project_id: str, session_id: str, window_id: int, artifact_id: str, command: Json
    ) -> Json:
        def action(db: sqlite3.Connection, project: sqlite3.Row, payload: Json) -> str:
            obj = revisions.artifact(db, artifact_id)
            revisions.get(db, payload["revisionId"], artifact_id)
            if obj["adoptedRevisionId"] != payload["revisionId"] or obj["needsUpdate"]:
                raise ProjectError("CHECK_REQUIRED")
            checks.require_coverage(db, payload["revisionId"], payload["checkIds"])
            db.execute(
                "UPDATE artifacts SET confirmed_revision_id=? WHERE id=?",
                (payload["revisionId"], artifact_id),
            )
            return artifact_id

        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "confirmRevision",
            {"revisionId", "checkIds"},
            artifact_id,
            action,
        )

    def undo_adoption(
        self, project_id: str, session_id: str, window_id: int, adoption_id: str, command: Json
    ) -> Json:
        def action(db: sqlite3.Connection, project: sqlite3.Row, payload: Json) -> str:
            if payload["adoptionId"] != adoption_id:
                raise ProjectError("VALIDATION_FAILED", 422)
            return adoptions.undo(db, adoption_id)

        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "undoAdoption",
            {"adoptionId"},
            adoption_id,
            action,
        )

    def run_local_checks(
        self, project_id: str, session_id: str, window_id: int, command: Json
    ) -> Json:
        return self.write(
            project_id,
            session_id,
            window_id,
            command,
            "runLocalChecks",
            {"revisionIds", "ruleIds"},
            None,
            lambda db, _, payload: checks.run(db, payload, command["clientOperationId"]),
        )

    def get_check_report(
        self, project_id: str, session_id: str, window_id: int, check_id: str
    ) -> Json:
        return self.read(
            project_id, session_id, window_id, lambda db, _: checks.report(db, check_id)
        )
