"""Local speech capacity, observation evidence, rights and explicit mix editing."""

import copy
import hashlib
import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.storage import media, revisions
from app.storage.errors import ProjectError
from app.storage.paths import relative_file
from app.storage.settings import canonical
from app.storage.task_plans import amount, identifier

Json = dict[str, Any]


def available_media(db: sqlite3.Connection, media_id: str) -> sqlite3.Row:
    row = media.media_row(db, identifier(media_id))
    database = db.execute("PRAGMA database_list").fetchone()[2]
    if row["availability"] != "available" or (
        database and media.dto(Path(database).parent, row)["availability"] != "available"
    ):
        raise ProjectError("MEDIA_MISSING", 422)
    return row


def time_range(value: Json, limit: int) -> tuple[int, int]:
    start, end = amount(value["startMs"]), amount(value["endMs"])
    if not start < end <= limit:
        raise ProjectError("TIME_RANGE_INVALID", 422)
    return start, end


def merged(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def dialogue(db: sqlite3.Connection, dialogue_id: str, revision_id: str | None = None) -> Json:
    if revision_id:
        rows = db.execute(
            "SELECT DISTINCT r.payload_json FROM revisions r JOIN dependencies d "
            "ON d.from_revision_id=r.id JOIN artifacts a ON a.id=r.artifact_id "
            "WHERE d.to_revision_id=? AND a.kind='story'",
            (revision_id,),
        )
    else:
        rows = db.execute(
            "SELECT r.payload_json FROM revisions r JOIN artifacts a "
            "ON a.adopted_revision_id=r.id WHERE a.kind='story'"
        )
    found = [
        item
        for row in rows
        for item in json.loads(row[0])["content"].get("dialogues", [])
        if item["id"] == dialogue_id
    ]
    if len(found) != 1:
        raise ProjectError("DIALOGUE_MAPPING_UNKNOWN", 422)
    result: Json = found[0]
    return result


def validate_formal(db: sqlite3.Connection, payload: Json, revision_id: str | None = None) -> None:
    """Called after schema validation, including on re-adoption and local checks."""
    kind, content = payload["kind"], payload["content"]
    if kind == "speech":
        row = available_media(db, content["mediaId"])
        if not row["mime"].startswith("audio/") or row["duration_ms"] is None:
            raise ProjectError("AUDIO_FORMAT_UNSUPPORTED", 422)
        if content["measuredMs"] != row["duration_ms"]:
            raise ProjectError("AUDIO_DURATION_MISMATCH", 422)
        if content["timingMethod"] == "provider_word":
            timing = json.loads(row["source_json"]).get("timing", {})
            if (
                timing.get("method") != "provider_word"
                or timing.get("mediaHash") != row["sha256"]
                or not isinstance(timing.get("wordRanges"), list)
                or not timing["wordRanges"]
            ):
                raise ProjectError("WORD_TIMING_UNAVAILABLE", 422)
            for word in timing["wordRanges"]:
                time_range(word, row["duration_ms"])
        windows = [time_range(item, row["duration_ms"]) for item in content["voicedRanges"]]
        if windows != sorted(windows) or any(
            a[1] > b[0] for a, b in zip(windows, windows[1:], strict=False)
        ):
            raise ProjectError("TIME_RANGE_INVALID", 422)
        source = dialogue(db, content["dialogueId"], revision_id)
        if source["speakerAssetId"] != content["speakerAssetId"]:
            raise ProjectError("DIALOGUE_MAPPING_UNKNOWN", 422)
    elif kind == "subtitle":
        source = None
        if content["audioRevisionId"]:
            audio = revisions.get(db, content["audioRevisionId"])
            if audio["payload"]["kind"] != "speech":
                raise ProjectError("VALIDATION_FAILED", 422)
            source = audio["payload"]["content"]
            validate_formal(db, audio["payload"], audio["id"])
        if content["timingMethod"] == "provider_word" and (
            source is None or source["timingMethod"] != "provider_word"
        ):
            raise ProjectError("WORD_TIMING_UNAVAILABLE", 422)
        cue_ids: set[str] = set()
        previous_start = -1
        for cue in content["cues"]:
            start, _ = time_range(cue["time"], source["measuredMs"] if source else 9007199254740991)
            if cue["id"] in cue_ids or start < previous_start:
                raise ProjectError("TIME_RANGE_INVALID", 422)
            previous_start = start
            cue_ids.add(cue["id"])
            if cue["dialogueId"]:
                text = dialogue(db, cue["dialogueId"], revision_id)["text"]
                if cue["differsFromDialogue"] != (cue["text"] != text):
                    raise ProjectError("SUBTITLE_DIFFERENCE_MISMATCH", 422)
                if source and cue["dialogueId"] != source["dialogueId"]:
                    raise ProjectError("DIALOGUE_MAPPING_UNKNOWN", 422)
    elif kind == "observation":
        row = available_media(db, content["mediaId"])
        if row["sha256"] != content["mediaHash"]:
            raise ProjectError("MEDIA_HASH_MISMATCH", 422)
        if not row["duration_ms"]:
            raise ProjectError("MEDIA_DURATION_REQUIRED", 422)
        observed = merged([time_range(item, row["duration_ms"]) for item in content["observed"]])
        usable = [time_range(item, row["duration_ms"]) for item in content["usable"]]
        problems = [time_range(item["time"], row["duration_ms"]) for item in content["problems"]]
        for start, end in usable + problems:
            if not any(left <= start < end <= right for left, right in observed):
                raise ProjectError("OBSERVATION_NOT_COVERED", 422)
        if any(a < d and c < b for a, b in usable for c, d in problems):
            raise ProjectError("OBSERVATION_CONFLICT", 422)


def current_revision(db: sqlite3.Connection, revision_id: str, kind: str) -> Json:
    item = revisions.get(db, identifier(revision_id))
    obj = revisions.artifact(db, item["artifactId"])
    if item["payload"]["kind"] != kind:
        raise ProjectError("VALIDATION_FAILED", 422)
    if (
        obj["adoptedRevisionId"] != revision_id
        or obj["needsUpdate"]
        or revisions.stale_inputs(db, revision_id)
    ):
        raise ProjectError("PLAN_STALE", 422)
    revisions.validate_payload(item["payload"])
    revisions.validate_references(db, item["payload"], revision_id)
    return item


def timing_check(db: sqlite3.Connection, payload: Json) -> Json:
    shot = current_revision(db, payload["shotRevisionId"], "shot")["payload"]["content"]
    ids = payload["speechRevisionIds"]
    if len(ids) != len(set(ids)) or len(ids) > 1000:
        raise ProjectError("VALIDATION_FAILED", 422)
    speeches = [current_revision(db, rid, "speech")["payload"]["content"] for rid in ids]
    mapped = {speech["dialogueId"]: speech for speech in speeches}
    if len(mapped) != len(speeches) or set(mapped) != set(shot["dialogueIds"]):
        raise ProjectError("DIALOGUE_MAPPING_UNKNOWN", 422)
    before, after = amount(payload["beforeMs"]), amount(payload["afterMs"])
    for speech in speeches:
        validate_formal(db, {"kind": "speech", "content": speech})
    audio_events = [event for event in shot["events"] if event["carrier"] == "audio"]
    if not audio_events:
        occupied = sum(speech["measuredMs"] for speech in speeches)
        fits_windows = True
    else:
        # Requirement IDs are the existing explicit dialogue/event mapping. Do not
        # guess parallel placement from speaker count or matching prose.
        occupied, fits_windows = 0, True
        used: set[str] = set()
        for speech in speeches:
            source = dialogue(db, speech["dialogueId"])
            matching = [
                event
                for event in audio_events
                if set(event["requirementIds"]) & set(source["requirementIds"])
            ]
            if len(matching) != 1 or matching[0]["id"] in used:
                raise ProjectError("TIMING_LAYOUT_AMBIGUOUS", 422)
            event = matching[0]
            used.add(event["id"])
            start, end = time_range(event["time"], shot["plannedMs"])
            occupied = max(occupied, start + speech["measuredMs"])
            fits_windows = fits_windows and speech["measuredMs"] <= end - start
    required = amount(before + occupied + after)
    shortage = max(0, required - shot["plannedMs"])
    return {
        "requiredMs": required,
        "plannedMs": shot["plannedMs"],
        "shortageMs": shortage,
        "method": "estimated"
        if any(s["timingMethod"] == "estimated" for s in speeches)
        else "measured",
        "suitable": shortage == 0 and fits_windows,
    }


def require_rights_schema(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] < 8:
        raise ProjectError("PROJECT_UPGRADE_REQUIRED", 409)


def verified_file_hash(db: sqlite3.Connection, media_id: str) -> str:
    row = available_media(db, media_id)
    database = db.execute("PRAGMA database_list").fetchone()[2]
    if not database:
        raise ProjectError("MEDIA_HASH_UNVERIFIABLE", 422)
    path = relative_file(Path(database).parent, row["relative_path"])
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        raise ProjectError("MEDIA_MISSING", 422) from None
    value = digest.hexdigest()
    if value != row["sha256"]:
        raise ProjectError("MEDIA_HASH_MISMATCH", 422)
    return value


def list_rights(db: sqlite3.Connection) -> Json:
    require_rights_schema(db)
    return {
        "items": [
            json.loads(row[0])
            for row in db.execute("SELECT payload_json FROM rights_evidence ORDER BY id")
        ]
    }


def save_rights(db: sqlite3.Connection, evidence_id: str, payload: Json) -> str:
    require_rights_schema(db)
    evidence = payload["evidence"]
    if identifier(evidence_id) != evidence["id"]:
        raise ProjectError("VALIDATION_FAILED", 422)
    row = available_media(db, evidence["mediaId"])
    ids = evidence["evidenceMediaIds"]
    if len(ids) != len(set(ids)):
        raise ProjectError("VALIDATION_FAILED", 422)
    hashes = {key: available_media(db, key)["sha256"] for key in ids}
    if evidence["state"] == "verified" and (not hashes or not evidence["explanation"].strip()):
        raise ProjectError("RIGHTS_VERIFICATION_REQUIRED", 422)
    if evidence["state"] == "verified":
        verified_file_hash(db, evidence["mediaId"])
        hashes = {key: verified_file_hash(db, key) for key in ids}
    now = datetime.now(UTC).isoformat()
    db.execute(
        "INSERT INTO rights_evidence(id,media_id,payload_json,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET media_id=excluded.media_id,"
        "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
        (evidence_id, evidence["mediaId"], canonical(evidence), now),
    )
    if evidence["state"] == "verified":
        db.execute(
            "INSERT INTO rights_verifications(id,evidence_id,media_hash,"
            "evidence_hashes_json,explanation,created_at) VALUES(?,?,?,?,?,?)",
            (
                str(uuid4()),
                evidence_id,
                row["sha256"],
                canonical(hashes),
                evidence["explanation"],
                now,
            ),
        )
    return evidence_id


def rights_verified(db: sqlite3.Connection, media_id: str) -> bool:
    require_rights_schema(db)
    row = available_media(db, media_id)
    for evidence_row in db.execute(
        "SELECT id,payload_json FROM rights_evidence WHERE media_id=?", (media_id,)
    ):
        evidence = json.loads(evidence_row["payload_json"])
        if evidence["state"] != "verified":
            continue
        verification = db.execute(
            "SELECT * FROM rights_verifications WHERE evidence_id=? ORDER BY rowid DESC LIMIT 1",
            (evidence_row["id"],),
        ).fetchone()
        if (
            verification is None
            or verification["media_hash"] != row["sha256"]
            or verification["explanation"] != evidence["explanation"]
        ):
            continue
        try:
            verified_file_hash(db, media_id)
            hashes = {key: verified_file_hash(db, key) for key in evidence["evidenceMediaIds"]}
        except ProjectError:
            continue
        if hashes and hashes == json.loads(verification["evidence_hashes_json"]):
            return True
    return False


def clip_media(db: sqlite3.Connection, clip: Json) -> str | None:
    if clip["mediaId"]:
        return str(clip["mediaId"])
    if clip["contentRevisionId"]:
        content = revisions.get(db, clip["contentRevisionId"])["payload"]["content"]
        media_id = content.get("mediaId") or content.get("videoMediaId")
        return str(media_id) if media_id else None
    return None


def audible_clip(clip: Json, track: Json) -> bool:
    if track["muted"] or clip["gainDb"] <= -96:
        return False
    keys = [key for key in clip["keyframes"] if key["property"] == "volume"]
    return not keys or any(key["value"] > 0 for key in keys)


def mix_warnings(db: sqlite3.Connection, timeline: Json) -> list[str]:
    tracks = {item["id"]: item for item in timeline["tracks"]}
    clips = [
        clip
        for clip in timeline["clips"]
        if audible_clip(clip, tracks[clip["trackId"]])
        and tracks[clip["trackId"]]["kind"] in {"voice", "music", "sfx", "video"}
    ]
    clips.sort(key=lambda clip: (clip["startMs"], clip["id"]))
    sources = {clip["id"]: clip_media(db, clip) for clip in clips}
    hashes = {key: available_media(db, key)["sha256"] for key in set(sources.values()) if key}
    rights = {
        key: rights_verified(db, key)
        for clip in clips
        if tracks[clip["trackId"]]["kind"] in {"music", "sfx"} and (key := sources[clip["id"]])
    }
    warnings: list[str] = []
    for index, clip in enumerate(clips):
        media_id = sources[clip["id"]]
        if (
            media_id
            and tracks[clip["trackId"]]["kind"] in {"music", "sfx"}
            and not rights[media_id]
        ):
            warnings.append("RIGHTS_UNVERIFIED:" + clip["id"])
        if clip["gainDb"] > 0:
            warnings.append("CLIPPING_RISK:" + clip["id"])
        for other in clips[index + 1 :]:
            if other["startMs"] >= clip["startMs"] + clip["durationMs"]:
                break
            if (
                clip["startMs"] >= other["startMs"] + other["durationMs"]
                or other["startMs"] >= clip["startMs"] + clip["durationMs"]
            ):
                continue
            other_media = sources[other["id"]]
            kinds = {tracks[clip["trackId"]]["kind"], tracks[other["trackId"]]["kind"]}
            if media_id and other_media and hashes[media_id] == hashes[other_media]:
                warnings.append("DUPLICATE_AUDIO:" + clip["id"] + ":" + other["id"])
            elif (
                kinds == {"video", "voice"} and clip["shotId"] and clip["shotId"] == other["shotId"]
            ):
                warnings.append("ORIGINAL_VOICE_OVERLAP:" + clip["id"] + ":" + other["id"])
            if len(warnings) >= 1000:
                return list(dict.fromkeys(warnings))[:1000]
    return list(dict.fromkeys(warnings))[:1000]


def ducking(db: sqlite3.Connection, payload: Json) -> Json:
    target = current_revision(db, payload["timelineRevisionId"], "timeline")
    timeline = copy.deepcopy(target["payload"]["content"])
    tracks = {item["id"]: item for item in timeline["tracks"]}
    selected = set(payload["musicClipIds"])
    if len(selected) != len(payload["musicClipIds"]) or not selected:
        raise ProjectError("VALIDATION_FAILED", 422)
    music = [clip for clip in timeline["clips"] if clip["id"] in selected]
    if len(music) != len(selected) or any(tracks[c["trackId"]]["kind"] != "music" for c in music):
        raise ProjectError("VALIDATION_FAILED", 422)
    attack, release = amount(payload["attackMs"]), amount(payload["releaseMs"])
    reduction = payload["reductionDb"]
    if (
        type(reduction) not in {int, float}
        or not math.isfinite(reduction)
        or not 0 <= reduction <= 96
        or attack > 10000
        or release > 10000
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    voiced: list[tuple[int, int]] = []
    for clip in timeline["clips"]:
        if tracks[clip["trackId"]]["kind"] != "voice" or not audible_clip(
            clip, tracks[clip["trackId"]]
        ):
            continue
        ranges = [(clip["inMs"], clip["outMs"])]
        if clip["contentRevisionId"]:
            speech = revisions.get(db, clip["contentRevisionId"])["payload"]
            if speech["kind"] == "speech" and clip_media(db, clip) != speech["content"]["mediaId"]:
                raise ProjectError("SPEECH_MEDIA_MISMATCH", 422)
            if speech["kind"] == "speech" and speech["content"]["voicedRanges"]:
                ranges = [(r["startMs"], r["endMs"]) for r in speech["content"]["voicedRanges"]]
        for start, end in ranges:
            start, end = max(start, clip["inMs"]), min(end, clip["outMs"])
            if start < end:
                voiced.append(
                    (clip["startMs"] + start - clip["inMs"], clip["startMs"] + end - clip["inMs"])
                )
    level = 10 ** (-reduction / 20)
    for clip in music:
        windows = merged(
            [
                (max(0, start - clip["startMs"]), min(clip["durationMs"], end - clip["startMs"]))
                for start, end in voiced
                if start < clip["startMs"] + clip["durationMs"] and end > clip["startMs"]
            ]
        )
        # Join nearby windows so release/attack never briefly raises music between words.
        joined: list[tuple[int, int]] = []
        for start, end in windows:
            if joined and start - joined[-1][1] <= attack + release:
                joined[-1] = (joined[-1][0], end)
            else:
                joined.append((start, end))
        if not joined:
            continue
        points: dict[int, float] = {0: 1.0, clip["durationMs"]: 1.0}
        jumps: set[int] = set()
        for start, end in joined:
            points[max(0, start - attack)] = 1.0
            points[start] = level
            points[min(clip["durationMs"], end + release)] = 1.0
            points[end] = level if release else 1.0
            if not attack:
                jumps.add(start)
            if not release:
                jumps.add(end)
        stamps = sorted(points)
        held = {stamps[index - 1] for index, stamp in enumerate(stamps) if index and stamp in jumps}
        clip["keyframes"] = [key for key in clip["keyframes"] if key["property"] != "volume"] + [
            {
                "timeMs": time,
                "property": "volume",
                "value": value,
                "interpolation": "hold" if time in held else "linear",
            }
            for time, value in sorted(points.items())
        ]
        clip["keyframes"].sort(key=lambda key: (key["timeMs"], key["property"]))
        if len(clip["keyframes"]) > 1000:
            raise ProjectError("KEYFRAME_LIMIT", 422)
    return {"timeline": timeline, "warnings": mix_warnings(db, timeline)}
