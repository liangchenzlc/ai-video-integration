"""Incomplete draft validation and transactional persistence using the T02 tables."""

import copy
import hashlib
import json
import sqlite3
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.storage.errors import ProjectError

Json = dict[str, Any]


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "draft.schema.json").read_text("utf-8")
    )
    return Draft202012Validator(schema)


def prepare_content(payload: Json) -> Json:
    """Preserve all input text and derive hashes from the exact UTF-8 source bytes."""
    if not _validator().is_valid(payload):
        raise ProjectError("VALIDATION_FAILED", 422)
    result = copy.deepcopy(payload)
    content = result["content"]
    if result["kind"] == "story" and "sourceText" in content:
        digest = hashlib.sha256(content["sourceText"].encode("utf-8")).hexdigest()
        if "sourceHash" in content and content["sourceHash"] != digest:
            raise ProjectError("VALIDATION_FAILED", 422)
        content["sourceHash"] = digest
    return result


def get(db: sqlite3.Connection, draft_id: str) -> Json:
    row = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    return {
        "id": row["id"],
        "artifactId": row["artifact_id"],
        "baseRevisionId": row["base_revision_id"],
        "content": json.loads(row["payload_json"]),
    }


def summaries(db: sqlite3.Connection) -> list[Json]:
    return [
        {
            "id": row["id"],
            "artifactId": row["artifact_id"],
            "kind": row["kind"],
            "savedAt": row["saved_at"],
        }
        for row in db.execute(
            "SELECT id,artifact_id,kind,saved_at FROM drafts ORDER BY saved_at DESC,id LIMIT 50"
        )
    ]


def store(db: sqlite3.Connection, payload: Json, content_json: str, saved_at: str) -> None:
    """Write inside the caller's receipt/revision transaction; never adopt the draft."""
    existing = db.execute("SELECT * FROM drafts WHERE id=?", (payload["draftId"],)).fetchone()
    kind = payload["content"]["kind"]
    if existing is not None and (
        existing["artifact_id"] != payload["artifactId"]
        or existing["base_revision_id"] != payload["baseRevisionId"]
        or existing["kind"] != kind
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    db.execute(
        """INSERT INTO drafts (id,artifact_id,base_revision_id,kind,payload_json,saved_at)
           VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
           payload_json=excluded.payload_json,saved_at=excluded.saved_at""",
        (
            payload["draftId"],
            payload["artifactId"],
            payload["baseRevisionId"],
            kind,
            content_json,
            saved_at,
        ),
    )
