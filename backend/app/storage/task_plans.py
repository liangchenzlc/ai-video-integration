"""Local immutable plans; no adapter submit, query or upload is used here."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.storage import drafts
from app.storage.errors import ProjectError
from app.storage.settings import canonical

Json = dict[str, Any]
STAGES = ("story", "image", "video", "speech", "lipsync", "music", "sfx", "check")
PHASES = (
    "story_adaptation",
    "story_outline",
    "story_scene",
    "story_dialogue",
    "image_character",
    "image_location",
    "image_prop",
    "image_keyframe",
    "video",
    "speech",
    "lipsync",
    "music",
    "sfx",
    "check",
)
CAPABILITY_ID = "00000000-0000-4000-8000-000000000004"


def amount(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 9007199254740991:
        raise ProjectError("VALIDATION_FAILED", 422)
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).version != 4:
        raise ProjectError("VALIDATION_FAILED", 422)
    return value


def digest(value: Json) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def input_snapshot(
    db: sqlite3.Connection, object_id: str, revision_ids: list[str] | None = None
) -> Json:
    from app.storage import revisions

    requested = revision_ids or []
    targets = [revisions.get(db, rid) for rid in requested]
    roots = [item for item in targets if item["artifactId"] == object_id]
    if len(roots) > 1:
        raise ProjectError("VALIDATION_FAILED", 422)
    if roots:
        root = roots[0]
        frozen = {
            "revisionId": root["id"],
            "kind": root["payload"]["kind"],
            "payload": root["payload"]["content"],
        }
        pending: list[tuple[str, str | None]] = [(root["id"], None)]
    else:
        row = db.execute(
            "SELECT * FROM drafts WHERE artifact_id=? ORDER BY saved_at DESC,id DESC LIMIT 1",
            (object_id,),
        ).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        content = drafts.prepare_content(json.loads(row["payload_json"]))
        frozen = {"draftId": row["id"], "kind": content["kind"], "payload": content["content"]}
        pending = [(rid, scope) for rid, scope, _ in revisions.revision_references(content)]
        pending.extend(revisions.stable_references(db, content))
    resolved: dict[str, Json] = {}
    while pending:
        rid, scope = pending.pop()
        # Check every incoming edge even if this revision was already traversed through
        # another scope. Only the explicit task root must still be the adopted revision.
        item = revisions.get(db, rid)
        if scope is None:
            obj = revisions.artifact(db, item["artifactId"])
            if obj["adoptedRevisionId"] != rid or obj["needsUpdate"]:
                raise ProjectError("PLAN_STALE")
        elif revisions.stale_reference(db, rid, scope):
            raise ProjectError("PLAN_STALE")
        if rid in resolved:
            continue
        revisions.validate_payload(item["payload"])
        revisions.validate_references(db, item["payload"], item["id"])
        resolved[rid] = item
        if len(resolved) > 1000:
            raise ProjectError("VALIDATION_FAILED", 422)
        pending.extend(
            (row[0], row[1])
            for row in db.execute(
                "SELECT from_revision_id,semantic_scope FROM dependencies WHERE to_revision_id=?",
                (rid,),
            )
        )
    if not set(requested) <= set(resolved):
        raise ProjectError("VALIDATION_FAILED", 422)
    if resolved:
        frozen["revisions"] = [resolved[key] for key in sorted(resolved)]
    return frozen


def input_media(db: sqlite3.Connection, frozen: Json, *, validate: bool) -> list[Json | None]:
    """Resolve every media field actually included in the frozen adapter input."""
    content = frozen["payload"]
    references = list(content.get("references", []))
    for key in ("mediaId", "videoMediaId"):
        if content.get(key) is not None:
            reference = {"mediaId": content[key]}
            if key == "mediaId" and "mediaHash" in content:
                reference["mediaHash"] = content["mediaHash"]
            references.append(reference)
    if "revisions" in frozen:
        from app.storage import revisions

        for item in frozen["revisions"]:
            for media_id, _, media_hash in revisions.media_references(item["payload"]["content"]):
                reference = {"mediaId": media_id}
                if media_hash is not None:
                    reference["mediaHash"] = media_hash
                references.append(reference)
    result: list[Json | None] = []
    seen = set()
    for reference in references:
        row = db.execute(
            "SELECT id,sha256,mime,availability FROM media_files WHERE id=?",
            (reference.get("mediaId"),),
        ).fetchone()
        if validate:
            if row is None or row["availability"] != "available":
                raise ProjectError("MEDIA_MISSING")
            if reference.get("mediaHash", row["sha256"]) != row["sha256"]:
                raise ProjectError("VALIDATION_FAILED", 422)
            if row["mime"].split("/")[0] not in {"image", "audio", "video"}:
                raise ProjectError("CAPABILITY_MISSING")
        media_id = reference.get("mediaId")
        if media_id not in seen:
            result.append(dict(row) if row is not None else None)
            seen.add(media_id)
    return result


def input_fingerprint(
    db: sqlite3.Connection,
    object_id: str,
    phase: str,
    precheck: bool,
    revision_ids: list[str] | None = None,
) -> str:
    frozen = input_snapshot(db, object_id, revision_ids)
    configurations = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM stage_models WHERE phase=? OR (phase='check' AND ?) ORDER BY phase",
            (phase, int(precheck)),
        )
    ]
    media = input_media(db, frozen, validate=False)
    return digest({"draft": frozen, "configuration": configurations, "media": media})


def compile_plan(db: sqlite3.Connection, project: sqlite3.Row, payload: Json, adapter: Any) -> Json:
    phase = payload["phase"]
    if phase not in PHASES or phase.split("_")[0] != payload["stage"]:
        raise ProjectError("VALIDATION_FAILED", 422)
    if (
        not isinstance(payload["inputRevisionIds"], list)
        or len(payload["inputRevisionIds"]) > 1000
        or len(set(payload["inputRevisionIds"])) != len(payload["inputRevisionIds"])
        or type(payload["candidates"]) is not int
        or not 1 <= payload["candidates"] <= 8
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    if (
        type(payload["includePrecheck"]) is not bool
        or not isinstance(payload["goal"], str)
        or not payload["goal"].strip()
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    mode = payload["executionMode"]
    if mode not in {"real", "synthetic"}:
        raise ProjectError("VALIDATION_FAILED", 422)
    if project["execution_mode"] not in {None, mode}:
        raise ProjectError("EXECUTION_MODE_MISMATCH")
    if mode != "synthetic":
        raise ProjectError("CAPABILITY_MISSING")
    frozen = input_snapshot(db, identifier(payload["objectId"]), payload["inputRevisionIds"])
    expected_kind = {
        "story": "story",
        "image": "asset",
        "video": "shot",
        "speech": "speech",
        "lipsync": "shot",
        "music": "shot",
        "sfx": "shot",
        "check": "observation",
    }[payload["stage"]]
    if frozen["kind"] != expected_kind:
        raise ProjectError("VALIDATION_FAILED", 422)
    content = frozen["payload"]
    required = {
        "story": ("sourceText", "brief"),
        "shot": ("purpose", "startState", "endState"),
        "asset": ("name", "assetType"),
        "speech": ("text",),
        "observation": ("mediaId",),
    }[frozen["kind"]]
    if any(not isinstance(content.get(key), str) or not content[key].strip() for key in required):
        raise ProjectError("INPUT_INCOMPLETE", 422)
    profile = adapter.describe(phase)
    refs = content.get("references", [])
    if len(refs) > profile["maxReferences"]:
        raise ProjectError("VALIDATION_FAILED", 422)
    media = input_media(db, frozen, validate=True)
    media_hashes = [row["sha256"] for row in media if row is not None]
    disclosure = ["text"] + sorted({row["mime"].split("/")[0] for row in media if row is not None})
    requested = content.get("plannedMs")
    if payload["stage"] in {"video", "lipsync", "music", "sfx"} and requested is None:
        raise ProjectError("INPUT_INCOMPLETE", 422)
    if requested is not None and profile["durationOptionsMs"]:
        supported = [value for value in profile["durationOptionsMs"] if value >= requested]
        if not supported:
            raise ProjectError("CAPABILITY_MISSING")
        requested = min(supported)
    steps, models = [], []
    for purpose in ["create"] + (["precheck"] if payload["includePrecheck"] else []):
        step_id = str(uuid4())
        price = amount(adapter.estimate(phase, requested, purpose))
        if price == 0:
            raise ProjectError("CAPABILITY_MISSING")
        steps.append(
            {
                "id": step_id,
                "purpose": purpose,
                "capabilityId": profile["id"],
                "maxCalls": payload["candidates"],
                "requestedMs": requested,
                "maxMicroCny": price,
                "disclosure": disclosure,
            }
        )
        models.append(
            {
                "stepId": step_id,
                "providerId": profile["providerId"],
                "modelId": profile["modelId"],
                "region": profile["region"],
                "capabilityVersion": profile["version"],
            }
        )
    plan = {
        key: payload[key]
        for key in (
            "objectId",
            "stage",
            "phase",
            "goal",
            "inputRevisionIds",
            "candidates",
            "executionMode",
        )
    }
    plan.update(
        id=str(uuid4()),
        steps=steps,
        models=models,
        inputMediaHashes=media_hashes,
        maximumMicroCny=amount(sum(step["maxMicroCny"] * step["maxCalls"] for step in steps)),
        priceVersion=profile["priceVersion"],
        templateVersion="synthetic-template-v1",
        expiresAt=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        inputPreview={"kind": frozen["kind"], "payload": frozen["payload"]},
    )
    if "revisions" in frozen:
        plan["inputRevisionIds"] = [item["id"] for item in frozen["revisions"]]
    db.execute(
        "INSERT INTO task_plans VALUES(?,?,?,?,?,?,?,?)",
        (
            plan["id"],
            payload["objectId"],
            payload["stage"],
            canonical(plan),
            input_fingerprint(
                db, payload["objectId"], phase, payload["includePrecheck"], plan["inputRevisionIds"]
            ),
            plan["maximumMicroCny"],
            plan["expiresAt"],
            mode,
        ),
    )
    for item in frozen.get("revisions", []):
        db.execute(
            "INSERT INTO task_plan_inputs VALUES(?,?,?)", (plan["id"], item["id"], canonical(item))
        )
    for ordinal, step in enumerate(steps):
        db.execute(
            "INSERT INTO planned_steps VALUES(?,?,?,?,?,?,?)",
            (
                step["id"],
                plan["id"],
                ordinal,
                step["purpose"],
                step["maxCalls"],
                step["maxMicroCny"],
                canonical(step),
            ),
        )
    db.execute("UPDATE projects SET execution_mode=? WHERE id=?", (mode, project["id"]))
    return plan


def get(db: sqlite3.Connection, plan_id: str) -> Json:
    row = db.execute(
        "SELECT plan_json FROM task_plans WHERE id=?", (identifier(plan_id),)
    ).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    result: Json = json.loads(row[0])
    return result


def validate_current(
    db: sqlite3.Connection, plan: Json, adapter: Any, *, expiry: bool = True
) -> None:
    row = db.execute("SELECT input_hash FROM task_plans WHERE id=?", (plan["id"],)).fetchone()
    profile = adapter.describe(plan["phase"])
    if (expiry and datetime.fromisoformat(plan["expiresAt"]) <= datetime.now(UTC)) or (
        row["input_hash"]
        != input_fingerprint(
            db,
            plan["objectId"],
            plan["phase"],
            any(step["purpose"] == "precheck" for step in plan["steps"]),
            plan["inputRevisionIds"],
        )
        or profile["priceVersion"] != plan["priceVersion"]
        or any(model["capabilityVersion"] != profile["version"] for model in plan["models"])
        or plan["templateVersion"] != "synthetic-template-v1"
    ):
        raise ProjectError("PLAN_STALE")
