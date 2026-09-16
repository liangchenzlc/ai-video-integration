"""Timeline semantics and non-destructive editing in integer milliseconds."""

import copy
import math
import sqlite3
from typing import Any
from uuid import uuid4

from app.storage.errors import ProjectError

Json = dict[str, Any]
VISUAL = {"image", "video"}
AUDIO = {"voice", "music", "sfx"}


def frame(ms: int, fps: Json) -> int:
    """Round a shared boundary once, half up, using integer arithmetic."""
    divisor = 1000 * fps["denominator"]
    return int((ms * fps["numerator"] * 2 + divisor) // (2 * divisor))


def invalid() -> None:
    raise ProjectError("TIMELINE_INVALID", 422)


def validate(
    content: Json, db: sqlite3.Connection | None = None, *, coverage: bool = False
) -> None:
    if (content["width"], content["height"]) not in {
        (1280, 720),
        (1920, 1080),
        (720, 1280),
        (1080, 1920),
    }:
        invalid()
    tracks = {track["id"]: track for track in content["tracks"]}
    clips = {clip["id"]: clip for clip in content["clips"]}
    if len(tracks) != len(content["tracks"]) or len(clips) != len(content["clips"]):
        invalid()
    if len({track["order"] for track in tracks.values()}) != len(tracks):
        invalid()
    for clip in clips.values():
        if clip["trackId"] not in tracks:
            invalid()
        kind = tracks[clip["trackId"]]["kind"]
        end = clip["startMs"] + clip["durationMs"]
        if clip["inMs"] >= clip["outMs"] or end > content["durationMs"]:
            invalid()
        if frame(end, content["fps"]) <= frame(clip["startMs"], content["fps"]):
            invalid()
        if kind not in {"image", "subtitle"} and clip["durationMs"] != clip["outMs"] - clip["inMs"]:
            invalid()
        if not clip["mediaId"] and not clip["contentRevisionId"]:
            invalid()
        links = clip["linkedClipIds"]
        if len(set(links)) != len(links) or clip["id"] in links or not set(links) <= clips.keys():
            invalid()
        points: set[tuple[str, int]] = set()
        for point in clip["keyframes"]:
            prop, value, stamp = point["property"], point["value"], point["timeMs"]
            if (prop, stamp) in points or stamp > clip["durationMs"] or not math.isfinite(value):
                invalid()
            points.add((prop, stamp))
            if prop == "scale" and not 0 < value <= 8:
                invalid()
            if prop == "opacity" and not 0 <= value <= 1:
                invalid()
            if prop == "volume" and not 0 <= value <= 4:
                invalid()
            if kind in AUDIO and prop != "volume" or kind == "image" and prop == "volume":
                invalid()
        if db is not None:
            media_id = clip["mediaId"]
            if clip["contentRevisionId"]:
                from app.storage import revisions

                source = revisions.get(db, clip["contentRevisionId"])["payload"]["content"]
                media_id = media_id or source.get("mediaId") or source.get("videoMediaId")
            if kind != "subtitle":
                row = db.execute("SELECT * FROM media_files WHERE id=?", (media_id,)).fetchone()
                if row is None or row["availability"] != "available":
                    raise ProjectError("MEDIA_NOT_AVAILABLE")
                mime = row["mime"]
                if kind == "image" and not mime.startswith("image/"):
                    invalid()
                if kind == "video" and mime != "video/mp4":
                    invalid()
                if kind in AUDIO and not mime.startswith(("audio/", "video/")):
                    invalid()
                if kind != "image" and (
                    row["duration_ms"] is None or clip["outMs"] > row["duration_ms"]
                ):
                    raise ProjectError("TIMELINE_MEDIA_SHORTAGE")
    transitions: dict[tuple[str, str], Json] = {}
    transition_ids: set[str] = set()
    for transition in content["transitions"]:
        pair = (transition["fromClipId"], transition["toClipId"])
        if transition["id"] in transition_ids or pair in transitions or pair[0] == pair[1]:
            invalid()
        transition_ids.add(transition["id"])
        if not set(pair) <= clips.keys():
            invalid()
        left, right = (clips[key] for key in pair)
        if left["trackId"] != right["trackId"] or tracks[left["trackId"]]["kind"] not in VISUAL:
            invalid()
        overlap = left["startMs"] + left["durationMs"] - right["startMs"]
        duration = transition["durationMs"]
        if left["startMs"] >= right["startMs"]:
            invalid()
        if transition["type"] == "cut" and (duration != 0 or overlap != 0):
            invalid()
        if transition["type"] == "dissolve" and (duration <= 0 or overlap != duration):
            invalid()
        if transition["type"] == "fade" and (duration <= 0 or overlap != 0):
            invalid()
        if duration >= min(left["durationMs"], right["durationMs"]):
            invalid()
        transitions[pair] = transition
    ranges = []
    for track in tracks.values():
        ordered = sorted(
            (c for c in clips.values() if c["trackId"] == track["id"]), key=lambda c: c["startMs"]
        )
        if track["kind"] not in VISUAL:
            continue
        for index, left in enumerate(ordered):
            if not track["muted"]:
                ranges.append((left["startMs"], left["startMs"] + left["durationMs"]))
            for right in ordered[index + 1 :]:
                if right["startMs"] >= left["startMs"] + left["durationMs"]:
                    break
                declared = transitions.get((left["id"], right["id"]))
                if declared is None or declared["type"] != "dissolve":
                    invalid()
    if coverage:
        end = 0
        for start, stop in sorted(ranges):
            if frame(start, content["fps"]) > frame(end, content["fps"]):
                raise ProjectError("TIMELINE_GAP")
            end = max(end, stop)
        if frame(end, content["fps"]) < frame(content["durationMs"], content["fps"]):
            raise ProjectError("TIMELINE_GAP")


def linked(content: Json, clip_id: str) -> set[str]:
    clips = {c["id"]: c for c in content["clips"]}
    tracks = {t["id"]: t for t in content["tracks"]}
    if clip_id not in clips:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    selected = {clip_id}
    while True:
        extra = {
            c["id"]
            for c in clips.values()
            if tracks[c["trackId"]]["kind"] in {"voice", "subtitle"}
            and (
                set(c["linkedClipIds"]) & selected
                or any(c["id"] in clips[key]["linkedClipIds"] for key in selected)
                or (
                    clips[clip_id]["shotId"] is not None and c["shotId"] == clips[clip_id]["shotId"]
                )
            )
        }
        if extra <= selected:
            return selected
        selected |= extra


def value_at(points: list[Json], prop: str, at: int, default: float) -> float:
    values = sorted((p for p in points if p["property"] == prop), key=lambda p: p["timeMs"])
    if not values:
        return default
    previous = values[0]
    if at <= previous["timeMs"]:
        return float(previous["value"])
    for following in values[1:]:
        if at < following["timeMs"]:
            if previous["interpolation"] == "hold":
                return float(previous["value"])
            fraction = (at - previous["timeMs"]) / (following["timeMs"] - previous["timeMs"])
            return float(previous["value"] + fraction * (following["value"] - previous["value"]))
        previous = following
    return float(previous["value"])


def sliced_keys(points: list[Json], start: int, end: int) -> list[Json]:
    result = [dict(p, timeMs=p["timeMs"] - start) for p in points if start <= p["timeMs"] <= end]
    for prop in {p["property"] for p in points}:
        for stamp in (start, end):
            if not any(p["property"] == prop and p["timeMs"] == stamp - start for p in result):
                prior = sorted(
                    (p for p in points if p["property"] == prop and p["timeMs"] <= stamp),
                    key=lambda p: p["timeMs"],
                )
                result.append(
                    {
                        "property": prop,
                        "timeMs": stamp - start,
                        "value": value_at(points, prop, stamp, 0),
                        "interpolation": prior[-1]["interpolation"] if prior else "linear",
                    }
                )
    return result


def edit(payload: Json) -> Json:
    content = copy.deepcopy(payload["timeline"])
    validate(content)
    clips = {c["id"]: c for c in content["clips"]}
    affected = linked(content, payload["clipId"])
    clip = clips[payload["clipId"]]
    tracks = {t["id"]: t for t in content["tracks"]}
    preview = []
    if payload["action"] == "move":
        delta = payload["startMs"] - clip["startMs"]
        for key in affected:
            clips[key]["startMs"] += delta
            if clips[key]["startMs"] < 0:
                invalid()
    elif payload["action"] == "split":
        stamp = payload["splitMs"]
        if not clip["startMs"] < stamp < clip["startMs"] + clip["durationMs"]:
            invalid()
        mapping = {}
        for key in sorted(affected):
            item = clips[key]
            offset = stamp - item["startMs"]
            if not 0 < offset < item["durationMs"]:
                continue
            right = copy.deepcopy(item)
            right["id"] = str(uuid4())
            mapping[key] = right["id"]
            right["startMs"] = stamp
            right["durationMs"] -= offset
            right["inMs"] += offset
            item["outMs"] = item["inMs"] + offset
            old_length = item["durationMs"]
            item["durationMs"] = offset
            right["keyframes"] = sliced_keys(item["keyframes"], offset, old_length)
            item["keyframes"] = sliced_keys(item["keyframes"], 0, offset)
            if tracks[item["trackId"]]["kind"] == "image":
                right["inMs"], right["outMs"] = item["inMs"], item["outMs"]
            if tracks[item["trackId"]]["kind"] == "subtitle":
                preview.append({"clipId": key, "splitMs": stamp})
            content["clips"].append(right)
        for item in content["clips"]:
            if item["id"] in mapping.values():
                item["linkedClipIds"] = [mapping.get(key, key) for key in item["linkedClipIds"]]
        for transition in content["transitions"]:
            transition["fromClipId"] = mapping.get(
                transition["fromClipId"], transition["fromClipId"]
            )
        affected |= set(mapping.values())
    elif payload["action"] == "trim":
        begin, end = payload["inMs"], payload["outMs"]
        length = payload.get("durationMs", end - begin)
        offset = begin - clip["inMs"]
        clip["keyframes"] = sliced_keys(clip["keyframes"], max(0, offset), max(0, offset) + length)
        clip.update(inMs=begin, outMs=end, durationMs=length)
        affected = {clip["id"]}
    else:
        invalid()
    content["durationMs"] = max(
        content["durationMs"], max(c["startMs"] + c["durationMs"] for c in content["clips"])
    )
    validate(content)
    return {
        "timeline": content,
        "affectedClipIds": sorted(affected),
        "subtitleSplitPreview": preview,
    }
