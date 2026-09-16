"""Checks limited to the submitted revision's reachable production inputs."""

import json
import sqlite3
from typing import Any

from app.storage import production_audio as audio
from app.storage import revisions, storyboard
from app.storage.errors import ProjectError

Json = dict[str, Any]
RULES = {"dialogue.timing", "rights.source", "requirement.coverage"}
LIMITATIONS = (
    "已核对本地媒体时长、来源核对记录和要求的承载区间。"
    "自然听感、授权有效性及内容表达效果仍需相应的人工核对证据。"
)


def _issue(code: str, evidence: str, severity: str = "blocking", time: Json | None = None) -> Json:
    return {
        "severity": severity,
        "message": code,
        "evidence": evidence,
        "time": time,
        "limitations": LIMITATIONS,
    }


def reachable(db: sqlite3.Connection, target: Json) -> list[Json]:
    result: dict[str, Json] = {}
    pending = [target]
    while pending:
        item = pending.pop()
        if item["id"] in result:
            continue
        result[item["id"]] = item
        if len(result) > 1000:
            raise ProjectError("REVISION_CHAIN_LIMIT", 422)
        pending.extend(
            revisions.get(db, row[0])
            for row in db.execute(
                "SELECT from_revision_id FROM dependencies WHERE to_revision_id=?",
                (item["id"],),
            )
        )
        pending.extend(
            revisions.get(db, rid) for rid, _, _ in revisions.revision_references(item["payload"])
        )
    return list(result.values())


def _enabled(clip: Json, track: Json, *, visual: bool = False) -> bool:
    if track["muted"] or (not visual and clip["gainDb"] <= -96):
        return False
    prop = "opacity" if visual else "volume"
    points = [key for key in clip["keyframes"] if key["property"] == prop]
    return not points or any(point["value"] > 0 for point in points)


def _audible_speeches(
    db: sqlite3.Connection, content: Json, speeches: list[Json], issues: list[Json]
) -> tuple[list[Json], dict[str, list[Json]]]:
    tracks = {track["id"]: track for track in content["tracks"]}
    sources = {speech["id"]: speech for speech in speeches}
    placements: dict[str, list[Json]] = {}
    for clip in content["clips"]:
        track = tracks[clip["trackId"]]
        if track["kind"] != "voice" or not _enabled(clip, track):
            continue
        source = sources.get(clip["contentRevisionId"])
        if not source:
            continue
        if audio.clip_media(db, clip) != source["payload"]["content"]["mediaId"]:
            issues.append(_issue("SPEECH_MEDIA_MISMATCH", clip["id"]))
            continue
        placements.setdefault(source["id"], []).append(clip)
    return [speech for speech in speeches if speech["id"] in placements], placements


def _timing(db: sqlite3.Connection, target: Json, chain: list[Json]) -> list[Json]:
    issues: list[Json] = []
    speeches = [item for item in chain if item["payload"]["kind"] == "speech"]
    timeline = target["payload"]["content"] if target["payload"]["kind"] == "timeline" else None
    speech_placements: dict[str, list[Json]] = {}
    if timeline:
        speeches, speech_placements = _audible_speeches(db, timeline, speeches, issues)
    for item in chain:
        if item["payload"]["kind"] in {"speech", "subtitle"}:
            try:
                audio.validate_formal(db, item["payload"], item["id"])
            except ProjectError as error:
                issues.append(_issue(error.code, item["id"]))
            if item["payload"]["content"]["timingMethod"] == "estimated":
                issues.append(_issue("TIMING_ESTIMATED", item["id"], "unknown_required"))
    for item in chain:
        if item["payload"]["kind"] != "shot":
            continue
        shot = item["payload"]["content"]
        wanted = set(shot["dialogueIds"])
        if not wanted:
            continue
        matching = [
            speech for speech in speeches if speech["payload"]["content"]["dialogueId"] in wanted
        ]
        if timeline:
            tracks = {track["id"]: track for track in timeline["tracks"]}
            visual_ranges = audio.merged(
                [
                    (clip["startMs"], clip["startMs"] + clip["durationMs"])
                    for clip in timeline["clips"]
                    if clip["shotId"] == shot["shotId"]
                    and tracks[clip["trackId"]]["kind"] in {"image", "video"}
                    and _enabled(clip, tracks[clip["trackId"]], visual=True)
                ]
            )
            for speech in matching:
                clips = [
                    clip
                    for clip in speech_placements[speech["id"]]
                    if clip["shotId"] == shot["shotId"]
                ]
                duration = speech["payload"]["content"]["measuredMs"]
                if audio.merged([(clip["inMs"], clip["outMs"]) for clip in clips]) != [
                    (0, duration)
                ]:
                    issues.append(_issue("SPEECH_RECORDING_INCOMPLETE", speech["id"]))
                for clip in clips:
                    if not any(
                        start <= clip["startMs"] and clip["startMs"] + clip["durationMs"] <= end
                        for start, end in visual_ranges
                    ):
                        issues.append(_issue("SPEECH_OUTSIDE_SHOT", clip["id"]))
        if target["payload"]["kind"] != "timeline":
            # Standalone shot checks can resolve its current adopted recordings.
            for row in db.execute(
                "SELECT r.id FROM revisions r JOIN artifacts a "
                "ON a.adopted_revision_id=r.id WHERE a.kind='speech'"
            ):
                speech = revisions.get(db, row[0])
                if speech["payload"]["content"]["dialogueId"] in wanted and speech["id"] not in {
                    s["id"] for s in matching
                }:
                    matching.append(speech)
        try:
            result = audio.timing_check(
                db,
                {
                    "shotRevisionId": item["id"],
                    "speechRevisionIds": [speech["id"] for speech in matching],
                    "beforeMs": 0,
                    "afterMs": 0,
                },
            )
            if not result["suitable"]:
                issues.append(_issue("SPEECH_EXCEEDS_SHOT", item["id"]))
        except ProjectError as error:
            issues.append(_issue(error.code, item["id"]))
    return issues


def _carrier_enabled(clip: Json, timeline: Json, event: Json, requirement: Json) -> bool:
    track = next(track for track in timeline["tracks"] if track["id"] == clip["trackId"])
    carrier, kind = event["carrier"], track["kind"]
    if carrier == "audio":
        return kind in {"voice", "music", "sfx", "video"} and _enabled(clip, track)
    if carrier == "subtitle":
        return kind == "subtitle" and timeline["burnSubtitles"] and not track["muted"]
    if carrier == "screenText" and kind == "subtitle":
        return bool(timeline["burnSubtitles"] and not track["muted"])
    if carrier in {"visual", "screenText"}:
        if requirement["category"] == "action" and kind != "video":
            return False
        return kind in {"image", "video"} and _enabled(clip, track, visual=True)
    return False


def _rights(db: sqlite3.Connection, chain: list[Json]) -> list[Json]:
    issues: list[Json] = []
    # Story reference assets are part of the frozen chain; unrelated project media are not.
    media_ids = {
        media_id
        for item in chain
        for media_id, _, _ in revisions.media_references(item["payload"]["content"])
    }
    for media_id in sorted(media_ids):
        try:
            if not audio.rights_verified(db, media_id):
                issues.append(_issue("RIGHTS_VERIFICATION_REQUIRED", media_id, "unknown_required"))
        except ProjectError as error:
            issues.append(_issue(error.code, media_id))
    return issues


def _reviewable_previews(db: sqlite3.Connection, target: Json) -> set[str]:
    if target["payload"]["kind"] != "timeline":
        return set()
    result: set[str] = set()
    for row in db.execute(
        "SELECT m.id,m.source_json,p.plan_json,p.input_hash FROM media_files m "
        "JOIN render_plans p ON p.id=json_extract(m.source_json,'$.renderPlanId') "
        "JOIN local_jobs j ON j.id=json_extract(m.source_json,'$.jobId') "
        "WHERE m.provenance='derived' AND m.availability='available' "
        "AND j.kind='animatic' AND j.state='succeeded' AND j.result_id=m.id "
        "AND p.timeline_revision_id=?",
        (target["id"],),
    ):
        plan = json.loads(row["plan_json"])
        source = json.loads(row["source_json"])
        if (
            plan.get("timelineRevisionId") == target["id"]
            and plan.get("timeline", {}).get("burnSubtitles")
            == target["payload"]["content"]["burnSubtitles"]
            and source.get("inputHash") == row["input_hash"] == plan.get("inputHash")
        ):
            result.add(row["id"])
    return result


def _subtitle_covers(db: sqlite3.Connection, clip: Json, event: Json) -> bool:
    if not clip["contentRevisionId"]:
        return False
    subtitle = revisions.get(db, clip["contentRevisionId"])["payload"]
    if subtitle["kind"] != "subtitle":
        return False
    ranges = audio.merged(
        [
            (
                max(cue["time"]["startMs"], clip["inMs"]),
                min(cue["time"]["endMs"], clip["inMs"] + clip["durationMs"]),
            )
            for cue in subtitle["content"]["cues"]
            if cue["text"].strip()
            and cue["time"]["startMs"] < clip["inMs"] + clip["durationMs"]
            and cue["time"]["endMs"] > clip["inMs"]
        ]
    )
    return any(
        start <= event["time"]["startMs"] and event["time"]["endMs"] <= end for start, end in ranges
    )


def _observed_usable(observation: Json, start: int, end: int) -> bool:
    return any(
        left <= start < end <= right
        for left, right in audio.merged(
            [(window["startMs"], window["endMs"]) for window in observation["usable"]]
        )
    )


def _requirements(db: sqlite3.Connection, target: Json, chain: list[Json]) -> list[Json]:
    issues: list[Json] = []
    stories = [item for item in chain if item["payload"]["kind"] == "story"]
    shots = [item for item in chain if item["payload"]["kind"] == "shot"]
    requirements: dict[str, tuple[Json, Json]] = {}
    if target["payload"]["kind"] == "shot":
        wanted = set(target["payload"]["content"]["requirementIds"])
    else:
        wanted = None
    for story in stories:
        try:
            storyboard.require_current_source_spans(story["payload"])
        except ProjectError as error:
            issues.append(_issue(error.code, story["id"]))
        content = story["payload"]["content"]
        for requirement in content.get("requirements", []):
            if requirement["required"] and (wanted is None or requirement["id"] in wanted):
                requirements[requirement["id"]] = (requirement, content)
    carriers: dict[str, list[tuple[Json, Json]]] = {}
    for shot in shots:
        for event in shot["payload"]["content"]["events"]:
            if event["observer"] == "audience":
                for key in event["requirementIds"]:
                    carriers.setdefault(key, []).append((shot, event))
    observations: dict[str, list[Json]] = {}
    used_media = {
        key
        for item in chain
        for key, _, _ in revisions.media_references(item["payload"]["content"])
    }
    preview_ids = _reviewable_previews(db, target)
    used_media.update(preview_ids)
    for row in db.execute(
        "SELECT r.id,r.payload_json FROM revisions r JOIN artifacts a "
        "ON a.adopted_revision_id=r.id WHERE a.kind='observation' AND a.needs_update=0"
    ):
        payload = json.loads(row["payload_json"])
        observation = payload["content"]
        if observation["mediaId"] in used_media and observation["method"] == "human":
            try:
                audio.validate_formal(db, payload, row["id"])
                if observation["mediaId"] in preview_ids:
                    audio.verified_file_hash(db, observation["mediaId"])
                observations.setdefault(observation["mediaId"], []).append(observation)
            except ProjectError:
                continue
    timeline = target["payload"]["content"] if target["payload"]["kind"] == "timeline" else None
    tracks = {track["id"]: track for track in timeline["tracks"]} if timeline else {}
    for key, (requirement, story) in requirements.items():
        decision = requirement["decision"]
        if decision == "unresolved" or (
            decision in {"omit", "replace"}
            and (not requirement["decisionReason"].strip() or not story["adaptationNotes"])
        ):
            issues.append(_issue("REQUIREMENT_DECISION_REQUIRED", key))
            continue
        if decision == "omit":
            continue
        matching = carriers.get(key, [])
        if not matching:
            issues.append(_issue("REQUIREMENT_CARRIER_MISSING", key))
            continue
        covered, reviewed = False, False
        for shot, event in matching:
            content = shot["payload"]["content"]
            placements = (
                [
                    clip
                    for clip in timeline["clips"]
                    if clip["shotId"] == content["shotId"]
                    and _carrier_enabled(clip, timeline, event, requirement)
                    and (
                        tracks[clip["trackId"]]["kind"] != "subtitle"
                        or _subtitle_covers(db, clip, event)
                    )
                    and clip["inMs"] <= event["time"]["startMs"]
                    and event["time"]["endMs"] <= clip["outMs"]
                ]
                if timeline
                else [None]
            )
            if not placements:
                continue
            covered = True
            for clip in placements:
                subtitle_clip = bool(clip and tracks[clip["trackId"]]["kind"] == "subtitle")
                # A source audio observation cannot establish rendered subtitle readability.
                media_id = (
                    None
                    if subtitle_clip
                    else audio.clip_media(db, clip)
                    if clip
                    else content.get("videoMediaId")
                )
                for observation in observations.get(media_id or "", []):
                    if _observed_usable(
                        observation, event["time"]["startMs"], event["time"]["endMs"]
                    ):
                        reviewed = True
                if clip:
                    absolute_start = clip["startMs"] + event["time"]["startMs"] - clip["inMs"]
                    absolute_end = clip["startMs"] + event["time"]["endMs"] - clip["inMs"]
                    if any(
                        _observed_usable(observation, absolute_start, absolute_end)
                        for media_id in preview_ids
                        for observation in observations.get(media_id, [])
                    ):
                        reviewed = True
        if not covered:
            issues.append(_issue("REQUIREMENT_CARRIER_TRIMMED", key))
        elif not reviewed:
            issues.append(_issue("REQUIREMENT_HUMAN_OBSERVATION_REQUIRED", key, "unknown_required"))
    return issues


def evaluate(db: sqlite3.Connection, target: Json, rule: str) -> Json:
    if rule not in RULES:
        raise ProjectError("VALIDATION_FAILED", 422)
    chain = reachable(db, target)
    kinds = {item["payload"]["kind"] for item in chain}
    if rule == "dialogue.timing":
        if not kinds & {"speech", "subtitle", "shot"}:
            return {"outcome": "not_applicable", "issues": []}
        issues = _timing(db, target, chain)
    elif rule == "rights.source":
        if not any(revisions.media_references(item["payload"]["content"]) for item in chain):
            return {"outcome": "not_applicable", "issues": []}
        issues = _rights(db, chain)
    else:
        if target["payload"]["kind"] not in {"shot", "timeline"} or "story" not in kinds:
            return {"outcome": "not_applicable", "issues": []}
        issues = _requirements(db, target, chain)
    outcome = (
        "fail"
        if any(issue["severity"] == "blocking" for issue in issues)
        else "unknown"
        if issues
        else "pass"
    )
    return {"outcome": outcome, "issues": issues}
