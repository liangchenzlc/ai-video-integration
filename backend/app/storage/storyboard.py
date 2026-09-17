"""Stable storyboard index, reference evidence and deterministic coverage."""

import copy
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.storage import drafts
from app.storage.errors import ProjectError
from app.storage.settings import canonical
from app.storage.task_plans import identifier

Json = dict[str, Any]


def require_007(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] < 7:
        raise ProjectError("PROJECT_VERSION_UNSUPPORTED")


def shot_ids(db: sqlite3.Connection) -> list[str]:
    return [row[0] for row in db.execute("SELECT shot_id FROM storyboard_shots ORDER BY ordinal")]


def summaries(db: sqlite3.Connection) -> Json:
    require_007(db)
    rows = db.execute(
        "SELECT id,artifact_id,kind,saved_at FROM drafts WHERE kind IN "
        "('story','asset','shot') ORDER BY saved_at DESC,id LIMIT 5001"
    ).fetchall()
    if len(rows) > 5000:
        raise ProjectError("VALIDATION_FAILED", 422)
    return {
        "drafts": [
            {
                "id": r["id"],
                "artifactId": r["artifact_id"],
                "kind": r["kind"],
                "savedAt": r["saved_at"],
            }
            for r in rows
        ],
        "shotIds": shot_ids(db),
    }


def _purpose_hash(content: Json) -> str:
    value = copy.deepcopy(content)
    for ref in value.get("references", []):
        ref.pop("state", None)
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _latest_evidence(
    db: sqlite3.Connection, draft_id: str, media_id: str, role: str
) -> sqlite3.Row | None:
    result: sqlite3.Row | None = db.execute(
        "SELECT * FROM reference_verifications WHERE draft_id=? AND media_id=? AND role=? "
        "ORDER BY rowid DESC LIMIT 1",
        (draft_id, media_id, role),
    ).fetchone()
    return result


def _media(db: sqlite3.Connection, media_id: str) -> sqlite3.Row:
    row: sqlite3.Row | None = db.execute(
        "SELECT sha256,availability FROM media_files WHERE id=?", (identifier(media_id),)
    ).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    return row


def reference_usable(
    db: sqlite3.Connection, reference: Json, draft_id: str, content: Json | None = None
) -> bool:
    media_id = reference.get("mediaId")
    role = reference.get("role")
    digest = reference.get("mediaHash")
    if not media_id or not role or not digest or reference.get("state") != "verified":
        return False
    media = db.execute(
        "SELECT sha256,availability FROM media_files WHERE id=?", (media_id,)
    ).fetchone()
    if media is None or media["availability"] != "available" or media["sha256"] != digest:
        return False
    evidence = _latest_evidence(db, draft_id, media_id, role)
    if evidence is None:
        return False
    effective = content if content is not None else drafts.get(db, draft_id)["content"]["content"]
    return bool(
        evidence
        and evidence["matches_purpose"]
        and evidence["media_hash"] == digest
        and evidence["purpose_hash"] == _purpose_hash(effective)
    )


def downgrade_changed_references(db: sqlite3.Connection, draft_id: str, payload: Json) -> None:
    """Keep normal edits writable; old evidence remains available for audit."""
    if payload["kind"] not in {"shot", "asset"}:
        return
    content = payload["content"]
    for ref in content.get("references", []):
        if ref.get("state") == "verified" and not reference_usable(db, ref, draft_id, content):
            ref["state"] = "pending"


def index_draft(db: sqlite3.Connection, draft_id: str, artifact_id: str, payload: Json) -> None:
    require_007(db)
    kind, content = payload["kind"], payload["content"]
    if kind == "shot" and content.get("shotId"):
        shot_id = identifier(content["shotId"])
        current = db.execute(
            "SELECT shot_id FROM storyboard_shots WHERE artifact_id=?", (artifact_id,)
        ).fetchone()
        if current is not None and current[0] != shot_id:
            raise ProjectError("VALIDATION_FAILED", 422)
        owner = db.execute(
            "SELECT artifact_id FROM storyboard_shots WHERE shot_id=?", (shot_id,)
        ).fetchone()
        if owner is not None and owner[0] != artifact_id:
            raise ProjectError("VALIDATION_FAILED", 422)
        if current is None:
            ordinal = db.execute(
                "SELECT COALESCE(MAX(ordinal)+1,0) FROM storyboard_shots"
            ).fetchone()[0]
            db.execute(
                "INSERT INTO storyboard_shots VALUES(?,?,?)", (shot_id, artifact_id, ordinal)
            )
    if kind != "shot" and kind != "asset":
        return
    for ref in content.get("references", []):
        if ref.get("state") == "verified" and not reference_usable(db, ref, draft_id):
            raise ProjectError("CHECK_REQUIRED")


def validate_formal(db: sqlite3.Connection, payload: Json) -> None:
    require_007(db)
    kind, content = payload["kind"], payload["content"]
    if kind == "story":
        source = content["sourceText"]
        digest = content["sourceHash"]
        for requirement in content["requirements"]:
            span = requirement.get("source")
            if (
                span
                and span["sourceHash"] == digest
                and not (0 <= span["startCodePoint"] < span["endCodePoint"] <= len(source))
            ):
                raise ProjectError("VALIDATION_FAILED", 422)
        return
    if kind == "asset":
        active = set(shot_ids(db))
        for state in content["states"]:
            if state["fromShotId"] not in active or state["throughShotId"] not in active:
                raise ProjectError("VALIDATION_FAILED", 422)
            order = {shot_id: index for index, shot_id in enumerate(shot_ids(db))}
            if order[state["fromShotId"]] > order[state["throughShotId"]]:
                raise ProjectError("VALIDATION_FAILED", 422)
        return
    if kind != "shot":
        return
    active = set(shot_ids(db))
    pickup = content["pickupOfShotId"]
    if content["shotId"] not in active or (
        pickup is not None and (pickup not in active or pickup == content["shotId"])
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    required = set(content["requirementIds"])
    for event in content["events"]:
        span = event["time"]
        if (
            not set(event["requirementIds"]) <= required
            or not 0 <= span["startMs"] < span["endMs"] <= content["plannedMs"]
        ):
            raise ProjectError("VALIDATION_FAILED", 422)


def require_current_source_spans(payload: Json) -> None:
    """Keep historical spans in drafts/revisions, but block a stale confirmation."""
    if payload["kind"] != "story":
        return
    content = payload["content"]
    for requirement in content["requirements"]:
        span = requirement.get("source")
        if span is not None and (
            span["sourceHash"] != content["sourceHash"]
            or not 0 <= span["startCodePoint"] < span["endCodePoint"] <= len(content["sourceText"])
        ):
            raise ProjectError("CHECK_REQUIRED")


def reorder(db: sqlite3.Connection, payload: Json) -> str:
    require_007(db)
    ids = payload["shotIds"]
    current = shot_ids(db)
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 5000
        or len(ids) != len(current)
        or len(set(ids)) != len(ids)
        or set(ids) != set(current)
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    if ids == current:
        return str(ids[0])
    locked = {
        row[0]
        for row in db.execute(
            "SELECT DISTINCT r.artifact_id FROM task_inputs ti JOIN revisions r "
            "ON r.id=ti.revision_id JOIN user_tasks t ON t.id=ti.task_id WHERE t.active=1"
        )
    }
    affected = {row[0] for row in db.execute("SELECT artifact_id FROM storyboard_shots")}
    affected.update(
        row[0]
        for row in db.execute(
            "SELECT id FROM artifacts WHERE kind='timeline' AND adopted_revision_id IS NOT NULL"
        )
    )
    if locked & affected:
        raise ProjectError("INPUT_LOCKED")
    offset = len(current)
    db.execute("UPDATE storyboard_shots SET ordinal=ordinal+?", (offset,))
    for ordinal, shot_id in enumerate(ids):
        db.execute("UPDATE storyboard_shots SET ordinal=? WHERE shot_id=?", (ordinal, shot_id))
    # The order participates in all timing, coverage and timeline review obligations.
    db.execute(
        "UPDATE artifacts SET needs_update=1 WHERE kind IN ('shot','timeline') "
        "AND adopted_revision_id IS NOT NULL"
    )
    return str(ids[0])


def verify(db: sqlite3.Connection, payload: Json) -> str:
    require_007(db)
    draft_id, media_id, role = (
        identifier(payload["draftId"]),
        identifier(payload["mediaId"]),
        payload["role"],
    )
    if (
        type(payload["matchesPurpose"]) is not bool
        or not isinstance(role, str)
        or not 1 <= len(role) <= 100
        or not isinstance(payload["note"], str)
        or not 1 <= len(payload["note"]) <= 2000
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    draft = drafts.get(db, draft_id)
    if draft["content"]["kind"] not in {"shot", "asset"}:
        raise ProjectError("VALIDATION_FAILED", 422)
    references = draft["content"]["content"].get("references", [])
    selected = [r for r in references if r.get("mediaId") == media_id and r.get("role") == role]
    if len(selected) != 1:
        raise ProjectError("VALIDATION_FAILED", 422)
    media = _media(db, media_id)
    if media["availability"] != "available":
        raise ProjectError("MEDIA_MISSING")
    ref = selected[0]
    if ref.get("mediaHash") != media["sha256"]:
        raise ProjectError("MEDIA_HASH_MISMATCH")
    verification_id = str(uuid4())
    db.execute(
        "INSERT INTO reference_verifications VALUES(?,?,?,?,?,?,?,?,?)",
        (
            verification_id,
            draft_id,
            media_id,
            media["sha256"],
            role,
            _purpose_hash(draft["content"]["content"]),
            int(payload["matchesPurpose"]),
            payload["note"],
            datetime.now(UTC).isoformat(),
        ),
    )
    ref["state"] = "verified" if payload["matchesPurpose"] else "incompatible"
    db.execute(
        "UPDATE drafts SET payload_json=?,saved_at=? WHERE id=?",
        (canonical(draft["content"]), datetime.now(UTC).isoformat(), draft_id),
    )
    return verification_id


def freeze_reference_evidence(
    db: sqlite3.Connection, revision_id: str, draft_id: str, payload: Json
) -> None:
    if payload["kind"] not in {"shot", "asset"}:
        return
    for ref in payload["content"].get("references", []):
        if ref.get("state") != "verified":
            continue
        if not reference_usable(db, ref, draft_id):
            raise ProjectError("CHECK_REQUIRED")
        evidence = _latest_evidence(db, draft_id, ref["mediaId"], ref["role"])
        assert evidence is not None
        db.execute(
            "INSERT INTO revision_reference_verifications VALUES(?,?,?,?)",
            (revision_id, ref["mediaId"], ref["role"], evidence["id"]),
        )


def adopted_reference_usable(db: sqlite3.Connection, revision_id: str, ref: Json) -> bool:
    if ref.get("state") != "verified":
        return False
    media_id, digest, role = ref.get("mediaId"), ref.get("mediaHash"), ref.get("role")
    return bool(
        db.execute(
            "SELECT 1 FROM revision_reference_verifications rv JOIN reference_verifications v "
            "ON v.id=rv.verification_id JOIN media_files m ON m.id=rv.media_id "
            "WHERE rv.revision_id=? AND rv.media_id=? AND rv.role=? "
            "AND v.matches_purpose=1 AND v.media_hash=? AND m.sha256=? "
            "AND m.availability='available'",
            (revision_id, media_id, role, digest, digest),
        ).fetchone()
    )


def coverage(db: sqlite3.Connection) -> Json:
    from app.storage import revisions

    require_007(db)
    adopted = [
        (row["id"], json.loads(row["payload_json"]), bool(row["needs_update"]))
        for row in db.execute(
            "SELECT r.id,r.payload_json,a.needs_update FROM artifacts a JOIN revisions r ON "
            "a.adopted_revision_id=r.id"
        )
    ]
    stories = [p["content"] for _, p, _ in adopted if p["kind"] == "story"]
    shots = [
        p["content"]
        for rid, p, stale in adopted
        if p["kind"] == "shot" and not stale and not revisions.stale_inputs(db, rid)
    ]
    carried = {
        rid
        for shot in shots
        for event in shot.get("events", [])
        if event.get("observer") == "audience" and event.get("carrier")
        for rid in event.get("requirementIds", [])
    }
    assigned = {rid for shot in shots for rid in shot.get("requirementIds", [])} | carried
    unassigned: set[str] = set()
    unresolved: set[str] = set()
    for story in stories:
        source = story.get("sourceText", "")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        for item in story.get("requirements", []):
            rid = item["id"]
            if not item.get("required"):
                continue
            span = item.get("source")
            stale = bool(
                span
                and (
                    span.get("sourceHash") != digest
                    or not 0
                    <= span.get("startCodePoint", -1)
                    < span.get("endCodePoint", -1)
                    <= len(source)
                )
            )
            decision = item.get("decision", "unresolved")
            explained = bool(
                item.get("decisionReason", "").strip() and story.get("adaptationNotes")
            )
            if (
                stale
                or decision == "unresolved"
                or (decision in {"omit", "replace"} and not explained)
            ):
                unresolved.add(rid)
            if decision == "keep" and rid not in carried:
                unassigned.add(rid)
            if decision in {"omit", "replace"} and not explained and rid not in assigned:
                unassigned.add(rid)
    invalid = {
        ref["mediaId"]
        for revision_id, payload, stale in adopted
        if payload["kind"] in {"asset", "shot"}
        for ref in payload["content"].get("references", [])
        if ref.get("mediaId")
        and (
            stale
            or revisions.stale_inputs(db, revision_id)
            or not adopted_reference_usable(db, revision_id, ref)
        )
    }
    if max(len(unassigned), len(unresolved), len(invalid)) > 1000:
        raise ProjectError("VALIDATION_FAILED", 422)
    return {
        "unassignedRequirementIds": sorted(unassigned),
        "unresolvedRequirementIds": sorted(unresolved),
        "invalidReferenceIds": sorted(invalid),
    }
