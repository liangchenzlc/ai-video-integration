"""Deterministic render checks; never claim semantic or listening acceptance."""

import sqlite3
from typing import Any

from app.storage import revisions, timeline
from app.storage.errors import ProjectError

Json = dict[str, Any]
RULES = {"timeline.bounds", "media.available", "audio.delivery"}


def evaluate(db: sqlite3.Connection, target: Json, rule: str) -> Json:
    payload = target["payload"]
    issues: list[Json] = []
    limitations = "仅核对本地素材、时间范围与重复声源；不代表听感、语义或艺术质量验收。"
    if rule not in RULES:
        raise ProjectError("VALIDATION_FAILED", 422)
    if rule != "media.available" and payload["kind"] != "timeline":
        return {"outcome": "not_applicable", "issues": []}
    try:
        if rule == "media.available":
            references = revisions.media_references(payload["content"])
            if payload["kind"] == "timeline":
                for clip in payload["content"]["clips"]:
                    if clip["contentRevisionId"]:
                        references.extend(
                            revisions.media_references(
                                revisions.get(db, clip["contentRevisionId"])["payload"]["content"]
                            )
                        )
            if not references:
                return {"outcome": "not_applicable", "issues": []}
            for media_id, _, expected_hash in references:
                row = db.execute(
                    "SELECT availability,sha256,relative_path FROM media_files WHERE id=?",
                    (media_id,),
                ).fetchone()
                if (
                    row is None
                    or row["availability"] != "available"
                    or expected_hash
                    and row["sha256"] != expected_hash
                ):
                    raise ProjectError("MEDIA_NOT_AVAILABLE")
                # Database resides inside the project; paths are validated without exposing them.
                from pathlib import Path

                from app.storage.paths import relative_file

                path = Path(db.execute("PRAGMA database_list").fetchone()[2]).parent
                if not relative_file(path, row["relative_path"]).is_file():
                    raise ProjectError("MEDIA_NOT_AVAILABLE")
        elif rule == "timeline.bounds":
            timeline.validate(payload["content"], db, coverage=True)
        else:
            content = payload["content"]
            tracks = {t["id"]: t for t in content["tracks"]}
            voices = [
                c
                for c in content["clips"]
                if tracks[c["trackId"]]["kind"] == "voice" and not tracks[c["trackId"]]["muted"]
            ]
            for index, left in enumerate(voices):
                for right in voices[index + 1 :]:
                    if (
                        left["mediaId"]
                        and left["mediaId"] == right["mediaId"]
                        or left["contentRevisionId"]
                        and left["contentRevisionId"] == right["contentRevisionId"]
                    ) and max(left["startMs"], right["startMs"]) < min(
                        left["startMs"] + left["durationMs"], right["startMs"] + right["durationMs"]
                    ):
                        issues.append(
                            {
                                "severity": "blocking",
                                "message": "相同配音在重叠区间重复播放，请核对并保留所需声源。",
                                "evidence": left["id"] + "," + right["id"],
                                "time": {
                                    "startMs": max(left["startMs"], right["startMs"]),
                                    "endMs": min(
                                        left["startMs"] + left["durationMs"],
                                        right["startMs"] + right["durationMs"],
                                    ),
                                },
                                "limitations": limitations,
                            }
                        )
    except (ProjectError, OSError) as error:
        issues.append(
            {
                "severity": "blocking",
                "message": error.code if isinstance(error, ProjectError) else "MEDIA_NOT_AVAILABLE",
                "evidence": "依据当前版本引用的时间线与本地素材记录。",
                "time": None,
                "limitations": limitations,
            }
        )
    return {"outcome": "fail" if issues else "pass", "issues": issues}
