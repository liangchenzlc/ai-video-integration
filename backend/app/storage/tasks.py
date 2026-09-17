"""Durable call transitions and public projections. The caller owns the transaction."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.storage import costs, task_plans
from app.storage.errors import ProjectError
from app.storage.settings import canonical


def now() -> str:
    return datetime.now(UTC).isoformat()


def event(db: sqlite3.Connection, call_id: str, kind: str, facts: dict[str, Any]) -> None:
    sequence = db.execute(
        "SELECT coalesce(max(event_sequence),0)+1 FROM call_events WHERE call_id=?", (call_id,)
    ).fetchone()[0]
    db.execute(
        "INSERT INTO call_events(call_id,event_sequence,event_type,facts_json,created_at) "
        "VALUES(?,?,?,?,?)",
        (call_id, sequence, kind, canonical(facts), now()),
    )


def task_event(db: sqlite3.Connection, task_id: str, state: str, active: bool = False) -> None:
    db.execute(
        "UPDATE user_tasks SET state=?,active=?,event_sequence=event_sequence+1 WHERE id=?",
        (state, int(active), task_id),
    )
    db.execute("UPDATE projects SET event_sequence=event_sequence+1")


def task(db: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM user_tasks WHERE id=?", (task_plans.identifier(task_id),)
    ).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    return {
        "id": row["id"],
        "planId": row["plan_id"],
        "state": row["state"],
        "eventSequence": row["event_sequence"],
        "observationStopped": bool(row["observation_stopped"]),
        "callIds": [
            r[0]
            for r in db.execute(
                "SELECT id FROM service_calls WHERE task_id=? ORDER BY rowid", (task_id,)
            )
        ],
        "candidateRevisionIds": (
            [
                r[0]
                for r in db.execute(
                    "SELECT c.revision_id FROM candidate_results c JOIN service_calls s "
                    "ON s.id=c.call_id WHERE s.task_id=? AND c.parse_state='registered' "
                    "AND c.revision_id IS NOT NULL ORDER BY c.rowid",
                    (task_id,),
                )
            ]
            if db.execute("PRAGMA user_version").fetchone()[0] >= 6
            else []
        ),
    }


def call(db: sqlite3.Connection, call_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT s.*,c.state billing_state,c.reserved_micro_cny,c.settled_micro_cny "
        "FROM service_calls s JOIN cost_entries c ON s.id=c.call_id WHERE s.id=?",
        (task_plans.identifier(call_id),),
    ).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    return {
        "id": row["id"],
        "taskId": row["task_id"],
        "stepId": row["step_id"],
        "submissionToken": row["submission_token"],
        "remoteTaskId": row["remote_task_id"],
        "state": row["state"],
        "resultMediaIds": (
            [
                item[0]
                for item in db.execute(
                    "SELECT media_id FROM candidate_results WHERE call_id=? "
                    "AND media_id IS NOT NULL ORDER BY result_ordinal",
                    (call_id,),
                )
            ]
            if db.execute("PRAGMA user_version").fetchone()[0] >= 6
            else []
        ),
        "billingState": row["billing_state"],
        "reservedMicroCny": row["reserved_micro_cny"],
        "settledMicroCny": row["settled_micro_cny"],
        "expiresAt": row["expires_at"],
        "providerId": row["provider_id"],
        "modelId": row["model_id"],
        "region": row["region"],
        "requestedAt": row["requested_at"],
        "errorCode": row["error_code"],
    }


def prepare_next(
    db: sqlite3.Connection, project: sqlite3.Row, task_id: str, adapter: Any
) -> str | None:
    row = db.execute("SELECT * FROM user_tasks WHERE id=?", (task_id,)).fetchone()
    plan = task_plans.get(db, row["plan_id"])
    task_plans.validate_current(db, plan, adapter, expiry=False)
    for step in plan["steps"]:
        submitted = db.execute(
            "SELECT count(*) FROM service_calls WHERE task_id=? AND step_id=?",
            (task_id, step["id"]),
        ).fetchone()[0]
        if submitted == step["maxCalls"]:
            continue
        costs.check_limits(
            db,
            project,
            plan["stage"],
            step["maxMicroCny"],
            task_id,
            row["authorized_maximum_micro_cny"],
        )
        model = next(model for model in plan["models"] if model["stepId"] == step["id"])
        call_id, token = str(uuid4()), str(uuid4())
        snapshot = {
            "inputPreview": plan["inputPreview"],
            "inputRevisions": [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT snapshot_json FROM task_plan_inputs WHERE plan_id=? ORDER BY "
                    "revision_id",
                    (plan["id"],),
                )
            ],
            "step": step,
            "model": model,
            "executionMode": plan["executionMode"],
            "stage": plan["stage"],
            "phase": plan["phase"],
            "inputMediaHashes": plan["inputMediaHashes"],
        }
        if step["purpose"] == "create" and plan["stage"] in {"story", "image"}:
            snapshot["resultProtocolVersion"] = "candidate-v1"
        db.execute(
            "INSERT INTO "
            "service_calls(id,task_id,step_id,ordinal,submission_token,provider_id,model_id,region,"
            "state,request_hash,request_snapshot_json,requested_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                call_id,
                task_id,
                step["id"],
                submitted,
                token,
                model["providerId"],
                model["modelId"],
                model["region"],
                "prepared",
                task_plans.digest(snapshot),
                canonical(snapshot),
                now(),
            ),
        )
        db.execute(
            "INSERT INTO cost_entries(call_id,state,reserved_micro_cny) VALUES(?,'pending',?)",
            (call_id, step["maxMicroCny"]),
        )
        event(db, call_id, "prepared", {"maximumMicroCny": step["maxMicroCny"]})
        return call_id
    return None


def cursor_rowid(
    db: sqlite3.Connection, table: str, key: str, cursor: str | None, limit: int
) -> int:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ProjectError("VALIDATION_FAILED", 422)
    if cursor is None:
        return 9223372036854775807
    if (table, key) not in {("user_tasks", "id"), ("cost_entries", "call_id")}:
        raise ValueError("Unsupported cursor table")
    row = db.execute(
        f"SELECT rowid FROM {table} WHERE {key}=?", (task_plans.identifier(cursor),)
    ).fetchone()
    if row is None:
        raise ProjectError("VALIDATION_FAILED", 422)
    return int(row[0])


def page(items: list[dict[str, Any]], key: str, limit: int) -> dict[str, Any]:
    return {
        "items": items[:limit],
        "nextCursor": items[limit - 1][key] if len(items) > limit else None,
    }


def summaries(db: sqlite3.Connection, cursor: str | None, limit: int) -> dict[str, Any]:
    before = cursor_rowid(db, "user_tasks", "id", cursor, limit)
    rows = db.execute(
        "SELECT t.*,p.object_id,p.stage,p.plan_json FROM user_tasks t "
        "JOIN task_plans p ON p.id=t.plan_id WHERE t.rowid<? ORDER BY t.rowid DESC LIMIT ?",
        (before, limit + 1),
    ).fetchall()
    return page(
        [
            {
                "id": row["id"],
                "planId": row["plan_id"],
                "objectId": row["object_id"],
                "stage": row["stage"],
                "phase": json.loads(row["plan_json"])["phase"],
                "state": row["state"],
                "eventSequence": row["event_sequence"],
                "observationStopped": bool(row["observation_stopped"]),
                "active": bool(row["active"]),
            }
            for row in rows
        ],
        "id",
        limit,
    )
