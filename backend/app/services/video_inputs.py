"""Offline video admission and durable upload lifecycle; no network adapter is invoked."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from app.storage import revisions
from app.storage.errors import ProjectError
from app.storage.production_audio import available_media, current_revision, dialogue, timing_check
from app.storage.task_plans import identifier

Json = dict[str, Any]


def validate_video_parameters(profile: Json, parameters: Json, *, has_speech: bool) -> None:
    """For an authorized future adapter's request builder, before prepare_inputs."""
    if has_speech and parameters.get("audio") is False:
        raise ProjectError("AUDIO_PARAMETER_CONFLICT", 422)
    if parameters.get("audioDrive") and not profile["supportsAudioDrive"]:
        raise ProjectError("AUDIO_DRIVE_UNSUPPORTED", 422)
    if parameters.get("lipsync") and not profile["supportsLipsync"]:
        raise ProjectError("LIPSYNC_UNSUPPORTED", 422)
    # Restriction tokens are deliberate machine-readable capability declarations.
    roles = set(parameters.get("referenceRoles", []))
    restrictions = set(profile["restrictions"])
    if "first_end_frame_exclusive" in restrictions and {"firstFrame", "endFrame"} <= roles:
        raise ProjectError("REFERENCE_PARAMETER_CONFLICT", 422)
    if (
        "frames_multi_reference_exclusive" in restrictions
        and roles & {"firstFrame", "endFrame"}
        and len(roles) > 1
    ):
        raise ProjectError("REFERENCE_PARAMETER_CONFLICT", 422)


def _preview_evidence(db: sqlite3.Connection, shot_id: str, production: bool) -> bool:
    required = {shot_id}
    if production:
        required = {row[0] for row in db.execute("SELECT shot_id FROM storyboard_shots")}
    rows = db.execute(
        "SELECT r.id,r.payload_json FROM revisions r JOIN artifacts a "
        "ON a.adopted_revision_id=r.id "
        "WHERE a.kind='timeline' AND a.confirmed_revision_id=r.id AND a.needs_update=0"
    ).fetchall()
    for row in rows:
        timeline = json.loads(row["payload_json"])["content"]
        if not required <= {clip["shotId"] for clip in timeline["clips"] if clip["shotId"]}:
            continue
        if revisions.stale_inputs(db, row["id"]):
            continue
        if db.execute(
            "SELECT 1 FROM local_jobs WHERE kind='animatic' AND state='succeeded' "
            "AND json_extract(snapshot_json,'$.timelineRevisionId')=?",
            (row["id"],),
        ).fetchone():
            return True
    return False


def readiness(db: sqlite3.Connection, payload: Json, profile: Json | None) -> Json:
    blockers: list[str] = []
    warnings = ["LOCAL_READINESS_ONLY: paid calls and uploads require a separate authorized task."]
    if payload["path"] not in {"research", "production"}:
        raise ProjectError("VALIDATION_FAILED", 422)
    try:
        target = current_revision(db, payload["shotRevisionId"], "shot")
        shot = target["payload"]["content"]
    except ProjectError as error:
        return {"ready": False, "blockers": [error.code], "warnings": warnings}
    obj = revisions.artifact(db, target["artifactId"])
    if payload["path"] == "production" and obj["confirmedRevisionId"] != target["id"]:
        blockers.append("SHOT_CONFIRMATION_REQUIRED")
    if not shot["references"]:
        blockers.append("REFERENCE_REQUIRED")
    if any(ref["state"] != "verified" for ref in shot["references"]):
        blockers.append("REFERENCE_VERIFICATION_REQUIRED")
    if not _preview_evidence(db, shot["shotId"], payload["path"] == "production"):
        blockers.append(
            "FULL_PREVIEW_CONFIRMATION_REQUIRED"
            if payload["path"] == "production"
            else "LOCAL_PREVIEW_CONFIRMATION_REQUIRED"
        )
    speeches: list[Json] = []
    for rid in payload["speechRevisionIds"]:
        try:
            speech = current_revision(db, rid, "speech")
            speech_obj = revisions.artifact(db, speech["artifactId"])
            if speech_obj["confirmedRevisionId"] != rid:
                blockers.append("SPEECH_CONFIRMATION_REQUIRED")
            if speech["payload"]["content"]["timingMethod"] == "estimated":
                blockers.append("SPEECH_TIMING_ESTIMATED")
            speeches.append(speech["payload"]["content"])
        except ProjectError as error:
            blockers.append(error.code)
    try:
        timing = timing_check(
            db,
            {
                "shotRevisionId": target["id"],
                "speechRevisionIds": payload["speechRevisionIds"],
                "beforeMs": 0,
                "afterMs": 0,
            },
        )
        if not timing["suitable"]:
            blockers.append("SPEECH_EXCEEDS_SHOT")
    except ProjectError as error:
        blockers.append(error.code)
    visible = [
        dialogue(db, key)
        for key in shot["dialogueIds"]
        if dialogue(db, key)["delivery"] == "visible"
    ]
    if (
        profile is None
        or not profile["enabled"]
        or profile["accountState"] != "available"
        or profile["interfaceState"] != "verified"
        or profile["stage"] not in {"video", "lipsync"}
    ):
        blockers.append("CAPABILITY_UNAVAILABLE")
    if profile:
        if visible and not (profile["supportsAudioDrive"] or profile["supportsLipsync"]):
            blockers.append("VISIBLE_DIALOGUE_UNSUPPORTED")
        if profile["supportsLipsync"] and not profile["supportsAudioDrive"] and visible:
            warnings.append("LIPSYNC_SEPARATE_AUTHORIZATION_REQUIRED")
        if payload["path"] == "production" and profile["qualityState"] != "verified":
            blockers.append("CAPABILITY_QUALITY_UNVERIFIED")
        elif profile["qualityState"] != "verified":
            warnings.append("CAPABILITY_RESEARCH_ONLY")
        if len(shot["references"]) > profile["maxReferences"] or any(
            ref["role"] not in profile["supportedReferenceRoles"] for ref in shot["references"]
        ):
            blockers.append("REFERENCE_CAPABILITY_UNSUPPORTED")
        try:
            validate_video_parameters(
                profile,
                {"referenceRoles": [ref["role"] for ref in shot["references"]]},
                has_speech=bool(speeches),
            )
        except ProjectError as error:
            blockers.append(error.code)
        options = profile["durationOptionsMs"]
        supported = [value for value in options if value >= shot["plannedMs"]]
        if options and not supported:
            blockers.append("DURATION_UNSUPPORTED")
        elif supported and min(supported) != shot["plannedMs"]:
            warnings.append(
                f"REQUEST_DURATION:{min(supported)};PLANNED_DURATION:{shot['plannedMs']}"
            )
        if (
            len({line["speakerAssetId"] for line in visible}) > 1
            and "single_speaker_only" in profile["restrictions"]
        ):
            blockers.append("MULTI_SPEAKER_UNSUPPORTED")
        if profile["restrictions"]:
            warnings.extend("CAPABILITY_RESTRICTION:" + item for item in profile["restrictions"])
    return {
        "ready": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": warnings[:1000],
    }


class UploadAdapter(Protocol):
    """Injectable boundary for a future approved provider; never constructed here."""

    def upload(self, *, object_key: str, media_id: str, checksum_sha256: str) -> None: ...

    def delete(self, *, object_key: str) -> None: ...


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, TypeError):
        raise ProjectError("VALIDATION_FAILED", 422) from None


class UploadLifecycle:
    """Transaction-only journal, called by prepare_inputs after task authorization.

    Persist register() before handing the object to an adapter. Unknown calls keep
    their inputs even if observation stopped or the application restarted.
    """

    @staticmethod
    def register(
        db: sqlite3.Connection,
        *,
        task_id: str,
        media_id: str,
        storage_profile_id: str,
        object_key: str,
        signed_until: str,
        retain_until: str,
        processing_limit_seconds: int,
        now: datetime | None = None,
    ) -> str:
        instant = now or datetime.now(UTC)
        task = db.execute(
            "SELECT t.*,p.execution_mode,p.plan_json,p.stage,p.maximum_micro_cny FROM user_tasks t "
            "JOIN task_plans p ON p.id=t.plan_id WHERE t.id=?",
            (identifier(task_id),),
        ).fetchone()
        if (
            task is None
            or task["state"] not in {"pending", "running"}
            or not task["active"]
            or task["execution_mode"] != "real"
            or task["stage"] not in {"video", "lipsync"}
            or task["authorized_maximum_micro_cny"] < task["maximum_micro_cny"]
        ):
            raise ProjectError("TASK_AUTHORIZATION_REQUIRED", 403)
        row = available_media(db, media_id)
        plan = json.loads(task["plan_json"])
        if row["sha256"] not in plan["inputMediaHashes"]:
            raise ProjectError("UPLOAD_INPUT_NOT_AUTHORIZED", 403)
        if type(processing_limit_seconds) is not int or not 1 <= processing_limit_seconds <= 604800:
            raise ProjectError("VALIDATION_FAILED", 422)
        expiry, retention = _instant(signed_until), _instant(retain_until)
        if expiry < instant + timedelta(seconds=processing_limit_seconds) or retention < expiry:
            raise ProjectError("UPLOAD_SIGNATURE_TOO_SHORT", 422)
        identifier(storage_profile_id)
        if (
            not isinstance(object_key, str)
            or not 1 <= len(object_key) <= 1024
            or any(c in object_key for c in "\r\n\x00")
        ):
            raise ProjectError("VALIDATION_FAILED", 422)
        previous = db.execute(
            "SELECT * FROM uploads WHERE storage_profile_id=? AND object_key=?",
            (storage_profile_id, object_key),
        ).fetchone()
        if previous:
            if (
                previous["task_id"] != task_id
                or previous["media_id"] != media_id
                or previous["checksum_sha256"] != row["sha256"]
            ):
                raise ProjectError("UPLOAD_OBJECT_CONFLICT", 409)
            if previous["state"] not in {"uploading", "available"}:
                raise ProjectError("UPLOAD_STATE_CONFLICT", 409)
            if previous["signed_until"] is None or _instant(
                previous["signed_until"]
            ) < instant + timedelta(seconds=processing_limit_seconds):
                raise ProjectError("UPLOAD_SIGNATURE_TOO_SHORT", 422)
            return str(previous["id"])
        upload_id = str(uuid4())
        db.execute(
            "INSERT INTO uploads(id,task_id,media_id,storage_profile_id,object_key,state,"
            "signed_until,retain_until,checksum_sha256) VALUES(?,?,?,?,?,'uploading',?,?,?)",
            (
                upload_id,
                task_id,
                media_id,
                storage_profile_id,
                object_key,
                signed_until,
                retain_until,
                row["sha256"],
            ),
        )
        return upload_id

    @staticmethod
    def complete(db: sqlite3.Connection, upload_id: str, checksum_sha256: str) -> None:
        row = db.execute("SELECT * FROM uploads WHERE id=?", (identifier(upload_id),)).fetchone()
        if row is None:
            raise ProjectError("OBJECT_NOT_FOUND", 404)
        if row["state"] not in {"uploading", "available"}:
            raise ProjectError("UPLOAD_STATE_CONFLICT", 409)
        if (
            row["checksum_sha256"] != checksum_sha256
            or available_media(db, row["media_id"])["sha256"] != checksum_sha256
        ):
            raise ProjectError("MEDIA_HASH_MISMATCH", 422)
        db.execute("UPDATE uploads SET state='available' WHERE id=?", (upload_id,))

    @staticmethod
    def require_available(
        db: sqlite3.Connection,
        task_id: str,
        processing_limit_seconds: int,
        now: datetime | None = None,
    ) -> list[Json]:
        instant = now or datetime.now(UTC)
        if type(processing_limit_seconds) is not int or not 1 <= processing_limit_seconds <= 604800:
            raise ProjectError("VALIDATION_FAILED", 422)
        task = db.execute(
            "SELECT t.*,p.execution_mode,p.plan_json,p.stage,p.maximum_micro_cny "
            "FROM user_tasks t JOIN task_plans p ON p.id=t.plan_id WHERE t.id=?",
            (identifier(task_id),),
        ).fetchone()
        if (
            task is None
            or task["state"] not in {"pending", "running"}
            or not task["active"]
            or task["execution_mode"] != "real"
            or task["stage"] not in {"video", "lipsync"}
            or task["authorized_maximum_micro_cny"] < task["maximum_micro_cny"]
        ):
            raise ProjectError("TASK_AUTHORIZATION_REQUIRED", 403)
        expected = set(json.loads(task["plan_json"])["inputMediaHashes"])
        rows = db.execute(
            "SELECT * FROM uploads WHERE task_id=?", (identifier(task_id),)
        ).fetchall()
        if expected != {row["checksum_sha256"] for row in rows}:
            raise ProjectError("UPLOAD_INPUTS_INCOMPLETE", 422)
        for row in rows:
            if (
                row["state"] != "available"
                or not row["signed_until"]
                or _instant(row["signed_until"])
                < instant + timedelta(seconds=processing_limit_seconds)
            ):
                raise ProjectError("UPLOAD_NOT_READY", 422)
            if available_media(db, row["media_id"])["sha256"] != row["checksum_sha256"]:
                raise ProjectError("MEDIA_HASH_MISMATCH", 422)
        return [dict(row) for row in rows]

    @staticmethod
    def mark_cleanup(db: sqlite3.Connection, now: datetime | None = None) -> list[Json]:
        instant = now or datetime.now(UTC)
        result = []
        rows = db.execute(
            "SELECT * FROM uploads WHERE state IN "
            "('available','failed','delete_pending','uploading')"
        ).fetchall()
        for row in rows:
            if row["retain_until"] is None or _instant(row["retain_until"]) > instant:
                continue
            active = db.execute(
                "SELECT 1 FROM user_tasks WHERE id=? AND (active=1 OR state IN "
                "('pending','running','result_unknown','pending_download')) UNION ALL "
                "SELECT 1 FROM service_calls WHERE task_id=? AND state IN "
                "('prepared','submitting','running','result_unknown','pending_download') LIMIT 1",
                (row["task_id"], row["task_id"]),
            ).fetchone()
            if active:
                continue
            db.execute("UPDATE uploads SET state='delete_pending' WHERE id=?", (row["id"],))
            result.append(dict(row) | {"state": "delete_pending"})
        return result

    @staticmethod
    def deletion_finished(db: sqlite3.Connection, upload_id: str, *, succeeded: bool) -> None:
        # A failed deletion stays durable and retryable; it never buys another generation.
        row = db.execute(
            "SELECT state FROM uploads WHERE id=?", (identifier(upload_id),)
        ).fetchone()
        if row is None or row["state"] != "delete_pending":
            raise ProjectError("UPLOAD_STATE_CONFLICT", 409)
        if succeeded:
            db.execute("UPDATE uploads SET state='deleted' WHERE id=?", (upload_id,))
