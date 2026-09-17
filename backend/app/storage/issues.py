"""Issue history and constrained decisions; evidence never resolves itself."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.storage.errors import ProjectError
from app.storage.settings import canonical
from app.storage.task_plans import identifier

Json = dict[str, Any]


def page(db: sqlite3.Connection, cursor: str | None, limit: int) -> Json:
    if not 1 <= limit <= 200:
        raise ProjectError("VALIDATION_FAILED", 422)
    offset = 0
    if cursor:
        row = db.execute("SELECT rowid FROM checks WHERE id=?", (identifier(cursor),)).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        offset = row[0]
    rows = db.execute(
        "SELECT rowid,* FROM checks WHERE rowid>? ORDER BY rowid LIMIT ?", (offset, limit + 1)
    ).fetchall()
    items = []
    for row in rows[:limit]:
        evidence = json.loads(row["evidence_json"])
        items.append(
            {
                "id": row["id"],
                "ruleId": row["rule_id"],
                "ruleVersion": row["rule_version"],
                "artifactId": row["artifact_id"],
                "revisionId": row["revision_id"],
                "baselineRevisionId": row["baseline_revision_id"],
                "severity": row["severity"],
                "status": row["status"],
                "message": evidence.get(
                    "message", evidence.get("errorCode", "请核对该版本的本地检查结果。")
                ),
                "evidence": evidence.get("evidence", ""),
                "time": evidence.get("time"),
                "method": row["method"],
                "limitations": evidence.get(
                    "limitations", "本地结构检查不代表内容语义或听感质量。"
                ),
            }
        )
    return {"items": items, "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None}


def decide(db: sqlite3.Connection, issue_id: str, payload: Json, operation_id: str) -> str:
    row = db.execute("SELECT * FROM checks WHERE id=?", (identifier(issue_id),)).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    action, reason, evidence = payload["action"], payload["reason"], payload["evidenceMediaIds"]
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ProjectError("VALIDATION_FAILED", 422)
    if action not in {"accept_deviation", "request_recheck", "attach_evidence"} or len(
        set(evidence)
    ) != len(evidence):
        raise ProjectError("VALIDATION_FAILED", 422)
    if action == "accept_deviation" and row["severity"] not in {"deviation", "advice"}:
        raise ProjectError("CHECK_BLOCKED")
    if action == "attach_evidence" and not evidence:
        raise ProjectError("VALIDATION_FAILED", 422)
    for media_id in evidence:
        media = db.execute(
            "SELECT availability FROM media_files WHERE id=?", (identifier(media_id),)
        ).fetchone()
        if media is None or media[0] != "available":
            raise ProjectError("MEDIA_MISSING")
    decision_id = str(uuid4())
    db.execute(
        "INSERT INTO check_decisions VALUES(?,?,?,?,?,?,?)",
        (
            decision_id,
            issue_id,
            action,
            reason.strip(),
            canonical(evidence),
            datetime.now(UTC).isoformat(),
            operation_id,
        ),
    )
    db.execute(
        "UPDATE checks SET status=? WHERE id=?",
        ("accepted_deviation" if action == "accept_deviation" else "recheck", issue_id),
    )
    return decision_id
