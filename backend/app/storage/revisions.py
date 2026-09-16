"""Immutable formal payloads and their indexed, validated references."""

import copy
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from app.storage import drafts
from app.storage.errors import ProjectError
from app.storage.semantic_scopes import changed_scopes
from app.storage.settings import canonical
from app.storage.task_plans import identifier

Json = dict[str, Any]


@cache
def validator() -> Draft202012Validator:
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/revision.schema.json").read_text("utf-8")
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_payload(payload: Json) -> None:
    if not validator().is_valid(payload):
        raise ProjectError("VALIDATION_FAILED", 422)
    if (
        payload["kind"] == "story"
        and payload["content"]["sourceHash"]
        != hashlib.sha256(payload["content"]["sourceText"].encode("utf-8")).hexdigest()
    ):
        raise ProjectError("VALIDATION_FAILED", 422)


def normalize(payload: Json) -> Json:
    result = copy.deepcopy(payload)
    content = result["content"]
    if result["kind"] == "story":
        content.setdefault("approvalLevel", "proposal")
        for field in ("outline", "requirements", "scenes", "dialogues", "adaptationNotes"):
            content.setdefault(field, [])
    try:
        validate_payload(result)
    except ProjectError:
        raise ProjectError("INPUT_INCOMPLETE", 422) from None
    if len(canonical(result).encode("utf-8")) > 700 * 1024:
        raise ProjectError("REVISION_SIZE_LIMIT", 422)
    return result


def artifact(db: sqlite3.Connection, artifact_id: str) -> Json:
    row = db.execute("SELECT * FROM artifacts WHERE id=?", (identifier(artifact_id),)).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    latest = db.execute(
        "SELECT id,artifact_id FROM adoptions WHERE undone=0 ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return {
        "id": row["id"],
        "kind": row["kind"],
        "adoptedRevisionId": row["adopted_revision_id"],
        "confirmedRevisionId": row["confirmed_revision_id"],
        "needsUpdate": bool(row["needs_update"]),
        "latestAdoptionId": latest["id"]
        if latest and latest["artifact_id"] == artifact_id
        else None,
    }


def get(db: sqlite3.Connection, revision_id: str, artifact_id: str | None = None) -> Json:
    row = db.execute("SELECT * FROM revisions WHERE id=?", (identifier(revision_id),)).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    if artifact_id is not None and row["artifact_id"] != artifact_id:
        raise ProjectError("VALIDATION_FAILED", 422)
    return {
        "id": row["id"],
        "artifactId": row["artifact_id"],
        "parentId": row["parent_id"],
        "payload": json.loads(row["payload_json"]),
        "contentHash": row["content_hash"],
        "createdAt": row["created_at"],
    }


def page(db: sqlite3.Connection, artifact_id: str, cursor: str | None, limit: int) -> Json:
    artifact(db, artifact_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ProjectError("VALIDATION_FAILED", 422)
    after = identifier(cursor) if cursor is not None else ""
    ids = [
        row[0]
        for row in db.execute(
            "SELECT id FROM revisions WHERE artifact_id=? AND id>? ORDER BY id LIMIT ?",
            (artifact_id, after, limit + 1),
        )
    ]
    items: list[Json] = []
    size = 0
    for revision_id in ids[:limit]:
        item = get(db, revision_id)
        item_size = len(canonical(item).encode("utf-8"))
        if items and size + item_size > 800 * 1024:
            break
        items.append(item)
        size += item_size
    return {"items": items, "nextCursor": items[-1]["id"] if len(ids) > len(items) else None}


def revision_references(payload: Json) -> list[tuple[str, str, str | None]]:
    content, kind = payload["content"], payload["kind"]
    result: list[tuple[str, str, str | None]] = [
        (rid, "identityVisual", "asset") for rid in content.get("assetRevisionIds", [])
    ]
    if content.get("audioRevisionId"):
        result.append((content["audioRevisionId"], "subtitleTiming", "speech"))
    if kind == "timeline":
        for clip in content["clips"]:
            if clip.get("contentRevisionId"):
                result.append((clip["contentRevisionId"], "timelinePlacement", None))
    return result


def media_references(value: Any, path: str = "content") -> list[tuple[str, str, str | None]]:
    result: list[tuple[str, str, str | None]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"mediaId", "videoMediaId"} and child is not None:
                result.append((child, path + "." + key, value.get("mediaHash")))
            else:
                result.extend(media_references(child, path + "." + key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(media_references(child, path + "." + str(index)))
    return result


def stable_references(
    db: sqlite3.Connection, payload: Json, revision_id: str | None = None
) -> list[tuple[str, str]]:
    content, kind = payload["content"], payload["kind"]
    if kind == "story":
        scenes = {item["id"] for item in content.get("scenes", [])}
        requirements = {item["id"] for item in content.get("requirements", [])}
        for dialogue in content.get("dialogues", []):
            if (
                dialogue["sceneId"] not in scenes
                or not set(dialogue["requirementIds"]) <= requirements
            ):
                raise ProjectError("VALIDATION_FAILED", 422)
        return []
    wanted: list[tuple[str, str, str]] = []
    if kind == "shot":
        if content.get("sceneId") is not None:
            wanted.append((content["sceneId"], "scenes", "revealTiming"))
        wanted.extend(
            (key, "requirements", "requirementCoverage")
            for key in content.get("requirementIds", [])
        )
        wanted.extend((key, "dialogues", "dialogueAudio") for key in content.get("dialogueIds", []))
    if kind == "speech" and content.get("dialogueId") is not None:
        wanted.append((content["dialogueId"], "dialogues", "dialogueAudio"))
    if kind == "subtitle":
        wanted.extend(
            (cue["dialogueId"], "dialogues", "subtitleTiming")
            for cue in content.get("cues", [])
            if cue["dialogueId"] is not None
        )
    if not wanted:
        return []
    if revision_id is None:
        rows = db.execute(
            "SELECT r.id,r.payload_json FROM revisions r JOIN artifacts a "
            "ON a.adopted_revision_id=r.id WHERE a.kind='story'"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT DISTINCT r.id,r.payload_json FROM dependencies d JOIN revisions r "
            "ON r.id=d.from_revision_id JOIN artifacts a ON a.id=r.artifact_id "
            "WHERE d.to_revision_id=? AND a.kind='story'",
            (revision_id,),
        ).fetchall()
    sources = [(row[0], json.loads(row[1])["content"]) for row in rows]
    result = []
    for key, collection, scope in wanted:
        found = [
            (rid, item) for rid, story in sources for item in story[collection] if item["id"] == key
        ]
        if len(found) != 1:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        rid, item = found[0]
        if kind == "speech" and item["speakerAssetId"] != content["speakerAssetId"]:
            raise ProjectError("VALIDATION_FAILED", 422)
        result.append((rid, scope))
    return result


def stale_reference(db: sqlite3.Connection, source_id: str, scope: str) -> bool:
    """Keep the exact historic input while checking its relevant current semantics."""
    source = get(db, source_id)
    obj = artifact(db, source["artifactId"])
    current_id = obj["adoptedRevisionId"]
    if current_id is None or obj["needsUpdate"]:
        return True
    if current_id == source_id:
        return False
    return scope in changed_scopes(source, get(db, current_id))


def stale_inputs(db: sqlite3.Connection, revision_id: str) -> bool:
    return any(
        stale_reference(db, row["from_revision_id"], row["semantic_scope"])
        for row in db.execute(
            "SELECT from_revision_id,semantic_scope FROM dependencies WHERE to_revision_id=?",
            (revision_id,),
        )
    )


def validate_references(
    db: sqlite3.Connection, payload: Json, revision_id: str | None = None
) -> None:
    stable_references(db, payload, revision_id)
    content = payload["content"]
    if payload["kind"] == "timeline":
        tracks = {item["id"] for item in content["tracks"]}
        clips = {item["id"] for item in content["clips"]}
        if len(tracks) != len(content["tracks"]) or len(clips) != len(content["clips"]):
            raise ProjectError("VALIDATION_FAILED", 422)
        for clip in content["clips"]:
            if (
                clip["trackId"] not in tracks
                or not set(clip["linkedClipIds"]) <= clips
                or (clip["mediaId"] is None and clip["contentRevisionId"] is None)
            ):
                raise ProjectError("VALIDATION_FAILED", 422)
        for transition in content["transitions"]:
            if transition["fromClipId"] not in clips or transition["toClipId"] not in clips:
                raise ProjectError("VALIDATION_FAILED", 422)
    for revision_id, _, kind in revision_references(payload):
        revision = get(db, revision_id)
        if kind is not None and revision["payload"]["kind"] != kind:
            raise ProjectError("VALIDATION_FAILED", 422)
    for media_id, _, digest in media_references(payload["content"]):
        row = db.execute(
            "SELECT sha256,availability FROM media_files WHERE id=?", (identifier(media_id),)
        ).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        if row["availability"] != "available":
            raise ProjectError("MEDIA_MISSING")
        if digest is not None and row["sha256"] != digest:
            raise ProjectError("MEDIA_HASH_MISMATCH")

    # Stable speaker IDs identify an asset, not its visual revision: changing a coat must not
    # invalidate independently recorded speech.
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("speakerAssetId") is not None:
                if artifact(db, value["speakerAssetId"])["kind"] != "asset":
                    raise ProjectError("VALIDATION_FAILED", 422)
            if value.get("locationAssetId") is not None:
                if artifact(db, value["locationAssetId"])["kind"] != "asset":
                    raise ProjectError("VALIDATION_FAILED", 422)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload["content"])


def create(db: sqlite3.Connection, artifact_id: str, draft_id: str) -> str:
    identifier(artifact_id)
    draft = drafts.get(db, identifier(draft_id))
    if draft["artifactId"] != artifact_id:
        raise ProjectError("VALIDATION_FAILED", 422)
    payload = normalize(draft["content"])
    existing = db.execute("SELECT kind FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
    if existing is not None and existing[0] != payload["kind"]:
        raise ProjectError("VALIDATION_FAILED", 422)
    if draft["baseRevisionId"] is not None:
        get(db, draft["baseRevisionId"], artifact_id)
    validate_references(db, payload)
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
            draft["baseRevisionId"],
            serialized,
            hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            datetime.now(UTC).isoformat(),
        ),
    )
    references = [
        (rid, scope) for rid, scope, _ in revision_references(payload)
    ] + stable_references(db, payload)
    for source, scope in references:
        if get(db, source)["artifactId"] == artifact_id:
            raise ProjectError("DEPENDENCY_CYCLE", 422)
        db.execute("INSERT OR IGNORE INTO dependencies VALUES(?,?,?)", (source, revision_id, scope))
    for ordinal, (media_id, role, _) in enumerate(media_references(payload["content"])):
        db.execute(
            "INSERT INTO revision_media VALUES(?,?,?,?)", (revision_id, media_id, role, ordinal)
        )
    return revision_id
