"""Durable provider results and immutable candidate revision registration."""

import copy
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from app.storage import revisions
from app.storage.errors import ProjectError
from app.storage.settings import canonical
from app.storage.task_plans import identifier

Json = dict[str, Any]
INVALID_RESULT = "STRUCTURED_RESULT_INVALID"

_STORY_MUTABLE = {
    "story_adaptation": {"brief", "requirements", "adaptationNotes", "approvalLevel"},
    "story_outline": {"outline", "approvalLevel"},
    "story_scene": {"scenes", "approvalLevel"},
    "story_dialogue": {"dialogues", "approvalLevel"},
}

_IMAGE_ROLES = {
    "image_character": "identity",
    "image_location": "location",
    "image_prop": "prop",
    "image_keyframe": "keyMoment",
}


def validate_image_envelope(raw_result: Any, snapshot: Json) -> None:
    synthetic = snapshot.get("executionMode") == "synthetic"
    if (
        snapshot.get("resultProtocolVersion") != "candidate-v1"
        or snapshot.get("stage") != "image"
        or snapshot.get("step", {}).get("purpose") != "create"
        or not isinstance(raw_result, dict)
        or raw_result.get("resultProtocolVersion") != "candidate-v1"
        or raw_result.get("resultType") != "image"
        or raw_result.get("synthetic") is not synthetic
        or (synthetic and raw_result.get("resultRef") is not None)
        or (
            not synthetic
            and (
                not isinstance(raw_result.get("resultRef"), str)
                or not raw_result["resultRef"].startswith("https://")
            )
        )
    ):
        raise ProjectError(INVALID_RESULT)


def _context(db: sqlite3.Connection, call_id: str) -> tuple[sqlite3.Row, Json, Json]:
    row = db.execute(
        "SELECT c.*,s.purpose,p.plan_json FROM service_calls c "
        "JOIN planned_steps s ON s.id=c.step_id "
        "JOIN user_tasks t ON t.id=c.task_id JOIN task_plans p ON p.id=t.plan_id "
        "WHERE c.id=?",
        (identifier(call_id),),
    ).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    return row, json.loads(row["request_snapshot_json"]), json.loads(row["plan_json"])


def retain_raw(
    db: sqlite3.Connection, call_id: str, result_ordinal: int, raw_result: Any
) -> sqlite3.Row:
    if type(result_ordinal) is not int or result_ordinal < 0:
        raise ProjectError("VALIDATION_FAILED", 422)
    serialized = canonical(raw_result)
    db.execute(
        "INSERT OR IGNORE INTO candidate_results"
        "(call_id,result_ordinal,raw_result_json,parse_state) VALUES(?,?,?,'pending')",
        (identifier(call_id), result_ordinal, serialized),
    )
    return cast(
        sqlite3.Row,
        db.execute(
            "SELECT * FROM candidate_results WHERE call_id=? AND result_ordinal=?",
            (call_id, result_ordinal),
        ).fetchone(),
    )


def invalidate(
    db: sqlite3.Connection, call_id: str, result_ordinal: int, result_kind: str = "text"
) -> None:
    db.execute(
        "UPDATE candidate_results SET parse_state='invalid',result_kind=?,"
        "error_code=? WHERE call_id=? AND result_ordinal=? AND parse_state='pending'",
        (result_kind, INVALID_RESULT, call_id, result_ordinal),
    )


def _validate_story(payload: Json, snapshot: Json, plan: Json) -> None:
    if payload.get("kind") != "story" or plan.get("stage") != "story":
        raise ProjectError(INVALID_RESULT)
    revisions.validate_payload(payload)
    source = dict(snapshot["inputPreview"]["payload"])
    source.setdefault("inputType", "idea")
    source.setdefault("approvalLevel", "proposal")
    for field in ("outline", "requirements", "scenes", "dialogues", "adaptationNotes"):
        source.setdefault(field, [])
    content = payload["content"]
    for field in ("sourceText", "sourceHash", "inputType"):
        if content[field] != source[field]:
            raise ProjectError(INVALID_RESULT)
    phase = plan.get("phase")
    mutable = _STORY_MUTABLE.get(phase) if isinstance(phase, str) else None
    if mutable is None:
        raise ProjectError(INVALID_RESULT)
    for field, value in source.items():
        if field not in mutable and content.get(field) != value:
            raise ProjectError(INVALID_RESULT)
    source_length = len(content["sourceText"])
    for requirement in content["requirements"]:
        span = requirement["source"]
        if span is not None and (
            span["sourceHash"] != content["sourceHash"]
            or span["startCodePoint"] >= span["endCodePoint"]
            or span["endCodePoint"] > source_length
        ):
            raise ProjectError(INVALID_RESULT)


def _create_revision(
    db: sqlite3.Connection, artifact_id: str, parent_id: str | None, payload: Json
) -> str:
    existing = db.execute("SELECT kind FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
    if existing is not None and existing[0] != payload["kind"]:
        raise ProjectError(INVALID_RESULT)
    if parent_id is not None:
        revisions.get(db, parent_id, artifact_id)
    revisions.validate_references(db, payload)
    db.execute(
        "INSERT OR IGNORE INTO artifacts(id,kind) VALUES(?,?)", (artifact_id, payload["kind"])
    )
    revision_id = str(uuid4())
    serialized = canonical(payload)
    db.execute(
        "INSERT INTO revisions VALUES(?,?,?,?,?,?)",
        (
            revision_id,
            artifact_id,
            parent_id,
            serialized,
            hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            datetime.now(UTC).isoformat(),
        ),
    )
    references = [
        (rid, scope) for rid, scope, _ in revisions.revision_references(payload)
    ] + revisions.stable_references(db, payload)
    for source, scope in references:
        if revisions.get(db, source)["artifactId"] == artifact_id:
            raise ProjectError(INVALID_RESULT)
        db.execute("INSERT OR IGNORE INTO dependencies VALUES(?,?,?)", (source, revision_id, scope))
    for ordinal, (media_id, role, _) in enumerate(revisions.media_references(payload["content"])):
        db.execute(
            "INSERT INTO revision_media VALUES(?,?,?,?)", (revision_id, media_id, role, ordinal)
        )
    return revision_id


def _parent_revision(db: sqlite3.Connection, task_id: str, artifact_id: str) -> str | None:
    row = db.execute(
        "SELECT r.id FROM task_inputs i JOIN revisions r ON r.id=i.revision_id "
        "WHERE i.task_id=? AND r.artifact_id=?",
        (task_id, artifact_id),
    ).fetchone()
    return None if row is None else str(row[0])


def register_text_result(
    db: sqlite3.Connection, call_id: str, result_ordinal: int, raw_result: Any
) -> str:
    row = retain_raw(db, call_id, result_ordinal, raw_result)
    if row["revision_id"] is not None:
        return str(row["revision_id"])
    if row["parse_state"] == "invalid":
        raise ProjectError(str(row["error_code"]))
    raw_result = json.loads(row["raw_result_json"])
    call, snapshot, plan = _context(db, call_id)
    db.execute("SAVEPOINT candidate_registration")
    try:
        if call["purpose"] != "create" or not isinstance(raw_result, dict):
            raise ProjectError(INVALID_RESULT)
        if raw_result.get("resultProtocolVersion") != "candidate-v1":
            raise ProjectError(INVALID_RESULT)
        payload = raw_result.get("payload")
        if not isinstance(payload, dict):
            raise ProjectError(INVALID_RESULT)
        _validate_story(payload, snapshot, plan)
        if len(canonical(payload).encode("utf-8")) > 700 * 1024:
            raise ProjectError(INVALID_RESULT)
        revisions.validate_references(db, payload)
        parent = _parent_revision(db, call["task_id"], plan["objectId"])
        revision_id = _create_revision(db, plan["objectId"], parent, payload)
        db.execute(
            "UPDATE candidate_results SET parse_state='registered',result_kind='text',"
            "revision_id=? WHERE call_id=? AND result_ordinal=? AND parse_state='pending'",
            (revision_id, call_id, result_ordinal),
        )
        db.execute("RELEASE candidate_registration")
        return revision_id
    except (ProjectError, KeyError, TypeError, ValueError):
        db.execute("ROLLBACK TO candidate_registration")
        db.execute("RELEASE candidate_registration")
        invalidate(db, call_id, result_ordinal)
        raise ProjectError(INVALID_RESULT) from None


def register_image_result(
    db: sqlite3.Connection,
    call_id: str,
    result_ordinal: int,
    raw_result: Any,
    media_id: str,
    media_hash: str,
) -> str:
    row = retain_raw(db, call_id, result_ordinal, raw_result)
    if row["revision_id"] is not None:
        if row["media_id"] != media_id:
            raise ProjectError("MEDIA_HASH_MISMATCH")
        return str(row["revision_id"])
    raw_result = json.loads(row["raw_result_json"])
    call, snapshot, plan = _context(db, call_id)
    db.execute("SAVEPOINT candidate_registration")
    try:
        validate_image_envelope(raw_result, snapshot)
        if call["purpose"] != "create" or plan.get("stage") != "image":
            raise ProjectError(INVALID_RESULT)
        role = _IMAGE_ROLES[plan["phase"]]
        content = copy.deepcopy(snapshot["inputPreview"]["payload"])
        references = content["references"]
        if len(references) >= 16:
            raise ProjectError(INVALID_RESULT)
        references.append(
            {
                "mediaId": media_id,
                "mediaHash": media_hash,
                "role": role,
                "order": len(references),
                "state": "pending",
                "keep": [],
                "ignore": [],
                "crop": None,
            }
        )
        payload = {"kind": snapshot["inputPreview"]["kind"], "content": content}
        if payload["kind"] not in {"asset", "shot"}:
            raise ProjectError(INVALID_RESULT)
        revisions.validate_payload(payload)
        if len(canonical(payload).encode("utf-8")) > 700 * 1024:
            raise ProjectError(INVALID_RESULT)
        revisions.validate_references(db, payload)
        parent = _parent_revision(db, call["task_id"], plan["objectId"])
        revision_id = _create_revision(db, plan["objectId"], parent, payload)
        db.execute(
            "UPDATE candidate_results SET parse_state='registered',result_kind='image',"
            "revision_id=?,media_id=? WHERE call_id=? AND result_ordinal=? "
            "AND parse_state='pending'",
            (revision_id, media_id, call_id, result_ordinal),
        )
        db.execute("RELEASE candidate_registration")
        return revision_id
    except (ProjectError, KeyError, TypeError, ValueError):
        db.execute("ROLLBACK TO candidate_registration")
        db.execute("RELEASE candidate_registration")
        invalidate(db, call_id, result_ordinal, "image")
        raise ProjectError(INVALID_RESULT) from None


def page(db: sqlite3.Connection, task_id: str, cursor: str | None, limit: int) -> Json:
    identifier(task_id)
    if db.execute("PRAGMA user_version").fetchone()[0] < 6:
        raise ProjectError("PROJECT_VERSION_UNSUPPORTED")
    if db.execute("SELECT 1 FROM user_tasks WHERE id=?", (task_id,)).fetchone() is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ProjectError("VALIDATION_FAILED", 422)
    after = 0
    if cursor is not None:
        row = db.execute(
            "SELECT c.rowid FROM candidate_results c JOIN service_calls s ON s.id=c.call_id "
            "WHERE s.task_id=? AND c.revision_id=? AND c.parse_state='registered'",
            (task_id, identifier(cursor)),
        ).fetchone()
        if row is None:
            raise ProjectError("VALIDATION_FAILED", 422)
        after = int(row[0])
    rows = db.execute(
        "SELECT c.rowid,c.revision_id FROM candidate_results c "
        "JOIN service_calls s ON s.id=c.call_id WHERE s.task_id=? "
        "AND c.parse_state='registered' AND c.revision_id IS NOT NULL AND c.rowid>? "
        "ORDER BY c.rowid LIMIT ?",
        (task_id, after, limit + 1),
    ).fetchall()
    items: list[Json] = []
    size = 0
    for row in rows[:limit]:
        item = revisions.get(db, row["revision_id"])
        item_size = len(canonical(item).encode("utf-8"))
        if items and size + item_size > 800 * 1024:
            break
        items.append(item)
        size += item_size
    return {"items": items, "nextCursor": items[-1]["id"] if len(rows) > len(items) else None}
