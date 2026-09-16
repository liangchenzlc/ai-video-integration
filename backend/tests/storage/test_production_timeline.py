"""B09: editing invariants and a short actual local animatic, no formal export."""

import copy
import hashlib
import json
import subprocess
from typing import Any
from uuid import uuid4

import pytest

from app.storage import timeline
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.production_fixtures import ProductionProject
from tests.storage.production_fixtures import production_project as production_project
from tests.storage.test_drafts import opened as opened
from tests.storage.test_media import FFMPEG, configure, wait_job
from tests.storage.test_versions import adopt, candidate, command, current

Json = dict[str, Any]


def clip(track: str, media: str | None, start: int, length: int, **fields: Any) -> Json:
    return {
        "id": str(uuid4()),
        "trackId": track,
        "shotId": None,
        "mediaId": media,
        "contentRevisionId": None,
        "startMs": start,
        "inMs": 0,
        "outMs": length,
        "durationMs": length,
        "gainDb": 0,
        "linkedClipIds": [],
        "keyframes": [],
        **fields,
    }


def basic_timeline() -> Json:
    tracks: list[Json] = [
        {"id": str(uuid4()), "kind": kind, "order": order, "muted": False}
        for order, kind in enumerate(("image", "voice", "subtitle", "music"))
    ]
    clips = [clip(track["id"], str(uuid4()), 0, 4000) for track in tracks]
    clips[0]["linkedClipIds"] = [clips[1]["id"], clips[2]["id"], clips[3]["id"]]
    return {
        "width": 1280,
        "height": 720,
        "fps": {"numerator": 24, "denominator": 1},
        "durationMs": 8000,
        "burnSubtitles": True,
        "tracks": tracks,
        "clips": clips,
        "transitions": [],
    }


def test_shared_frame_boundaries_and_zero_length_rejection() -> None:
    content = basic_timeline()
    fps = content["fps"]
    boundaries = [0, 4000, 8000, 12000, 17000, 22000, 26000, 30000]
    assert (
        sum(
            timeline.frame(b, fps) - timeline.frame(a, fps)
            for a, b in zip(boundaries, boundaries[1:], strict=False)
        )
        == 720
    )
    assert timeline.frame(29999, fps) == timeline.frame(30000, fps) == 720
    content["clips"][0]["durationMs"] = 1
    with pytest.raises(ProjectError, match="TIMELINE_INVALID"):
        timeline.validate(content)


def test_move_keeps_voice_subtitles_linked_and_music_fixed() -> None:
    content = basic_timeline()
    result = timeline.edit(
        {
            "timeline": content,
            "clipId": content["clips"][0]["id"],
            "action": "move",
            "startMs": 1000,
        }
    )
    assert [c["startMs"] for c in result["timeline"]["clips"]] == [1000, 1000, 1000, 0]
    assert [c["startMs"] for c in content["clips"]] == [0, 0, 0, 0]
    assert len(result["affectedClipIds"]) == 3


def test_split_preserves_source_ranges_and_previews_crossing_subtitle() -> None:
    content = basic_timeline()
    original = content["clips"][1]
    original.update(inMs=500, outMs=4500)
    original["keyframes"] = [
        {"timeMs": 0, "property": "volume", "value": 1, "interpolation": "linear"},
        {"timeMs": 4000, "property": "volume", "value": 0, "interpolation": "linear"},
    ]
    result = timeline.edit(
        {
            "timeline": content,
            "clipId": content["clips"][0]["id"],
            "action": "split",
            "splitMs": 2000,
        }
    )
    voices = [c for c in result["timeline"]["clips"] if c["trackId"] == original["trackId"]]
    assert [(c["inMs"], c["outMs"], c["startMs"], c["durationMs"]) for c in voices] == [
        (500, 2500, 0, 2000),
        (2500, 4500, 2000, 2000),
    ]
    assert next(p["value"] for p in voices[1]["keyframes"] if p["timeMs"] == 0) == pytest.approx(
        0.5
    )
    assert result["subtitleSplitPreview"] == [
        {"clipId": content["clips"][2]["id"], "splitMs": 2000}
    ]
    assert all(c["mediaId"] == original["mediaId"] for c in voices)


def test_transition_overlap_and_duplicate_keys_rejected() -> None:
    content = basic_timeline()
    content["clips"] = [content["clips"][0]]
    content["clips"][0]["linkedClipIds"] = []
    right = clip(content["tracks"][0]["id"], str(uuid4()), 3500, 4000)
    content["clips"].append(right)
    with pytest.raises(ProjectError, match="TIMELINE_INVALID"):
        timeline.validate(content)
    content["transitions"] = [
        {
            "id": str(uuid4()),
            "fromClipId": content["clips"][0]["id"],
            "toClipId": right["id"],
            "type": "dissolve",
            "durationMs": 500,
        }
    ]
    timeline.validate(content)
    point = {"timeMs": 0, "property": "opacity", "value": 1, "interpolation": "linear"}
    right["keyframes"] = [point, copy.deepcopy(point)]
    with pytest.raises(ProjectError, match="TIMELINE_INVALID"):
        timeline.validate(content)


def register_media(project: ProductionProject, name: str, color: str, duration: int | None) -> str:
    path = project.opened[1] / "media" / name
    args = [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=96x64:r=24"]
    args += (
        ["-frames:v", "1"]
        if duration is None
        else ["-t", str(duration / 1000), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    )
    subprocess.run([*args, str(path)], check=True, capture_output=True, timeout=20)
    media_id = str(uuid4())
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        db.execute(
            "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                media_id,
                "media/" + name,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_size,
                "image/png" if duration is None else "video/mp4",
                duration,
                96,
                64,
                "available",
                "imported",
                "{}",
            ),
        )
    return media_id


@pytest.mark.skipif(not FFMPEG.is_file(), reason="Selected repository FFmpeg fixture unavailable")
def test_replacement_reports_shortage_without_changing_adopted_edit(
    production_project: ProductionProject,
) -> None:
    project = production_project
    long = register_media(project, "long.mp4", "blue", 5000)
    short = register_media(project, "short.mp4", "red", 3000)
    content = basic_timeline()
    content["tracks"] = [dict(content["tracks"][0], kind="video")]
    content["clips"] = [clip(content["tracks"][0]["id"], long, 0, 5000)]
    content["durationMs"] = 5000
    artifact, revision = candidate(project.opened, kind="timeline", content=content)
    adopt(project.opened, artifact, revision)
    result = project.service._rendering.replacement_preview(
        *project.args,
        {
            "timelineRevisionId": revision,
            "clipId": content["clips"][0]["id"],
            "newMediaId": short,
        },
    )
    assert result["shortageMs"] == 2000
    assert result["canPreserveEdit"] is False
    stored = project.service.list_revisions(*project.args, artifact)["items"][0]
    assert stored["payload"]["content"] == content


@pytest.mark.skipif(not FFMPEG.is_file(), reason="Selected repository FFmpeg fixture unavailable")
def test_actual_animatic_graph_subtitles_audio_and_frozen_plan(
    production_project: ProductionProject,
) -> None:
    project = production_project
    configure(project.service)
    red = register_media(project, "镜头's red.png", "red", None)
    blue = register_media(project, "镜头 blue.png", "blue", None)
    subtitle = project.subtitle()
    subtitle["cues"][0]["time"]["endMs"] = 1400
    subtitle_artifact, subtitle_revision = candidate(
        project.opened, kind="subtitle", content=subtitle
    )
    adopt(project.opened, subtitle_artifact, subtitle_revision)
    content = basic_timeline()
    content["durationMs"] = 1400
    content["tracks"] = content["tracks"][:3]
    first = clip(content["tracks"][0]["id"], red, 0, 800)
    second = clip(content["tracks"][0]["id"], blue, 600, 800)
    second["keyframes"] = [
        {"timeMs": 0, "property": "opacity", "value": 1, "interpolation": "linear"},
        {"timeMs": 800, "property": "opacity", "value": 0.9, "interpolation": "linear"},
    ]
    content["clips"] = [
        first,
        second,
        clip(content["tracks"][1]["id"], project.media_id, 0, 1400, gainDb=-6),
        clip(content["tracks"][2]["id"], None, 0, 1400, contentRevisionId=subtitle_revision),
    ]
    content["transitions"] = [
        {
            "id": str(uuid4()),
            "fromClipId": first["id"],
            "toClipId": second["id"],
            "type": "dissolve",
            "durationMs": 200,
        }
    ]
    artifact, revision = candidate(project.opened, kind="timeline", content=content)
    adopt(project.opened, artifact, revision)
    plan = project.service._rendering.preview_render_plan(
        *project.args, {"timelineRevisionId": revision}
    )
    receipt = project.service._rendering.render_animatic(
        *project.args, command(current(project.opened), {"timelineRevisionId": revision})
    )
    job = wait_job(project.service, project.args, receipt)
    assert job["state"] == "succeeded", json.dumps(job)
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        row = db.execute("SELECT * FROM media_files WHERE id=?", (job["resultId"],)).fetchone()
        snapshot = json.loads(
            db.execute("SELECT snapshot_json FROM local_jobs WHERE id=?", (job["id"],)).fetchone()[
                0
            ]
        )
    assert snapshot["plan"]["inputHash"] == plan["inputHash"]
    assert snapshot["timelineRevisionId"] == revision
    assert row["width"] == 1280 and row["height"] == 720
    output = project.opened[1] / row["relative_path"]
    probe = subprocess.run(
        [
            str(FFMPEG.with_name("ffprobe.exe")),
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    streams = json.loads(probe.stdout)["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert video["nb_read_frames"] == "34"
    assert video["avg_frame_rate"] == "24/1"
    assert audio["codec_name"] == "aac" and audio["sample_rate"] == "48000"
    # Decode selected color frames to prove the graph carries both source images.
    for stamp, component in (("0.1", 0), ("1.2", 2)):
        sampled = subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-ss",
                stamp,
                "-i",
                str(output),
                "-vf",
                "crop=16:16:632:100,scale=1:1",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        assert sampled.stdout[component] > 180, sampled.stdout
    subtitle_pixels = subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            "0.1",
            "-i",
            str(output),
            "-vf",
            "crop=800:100:240:570",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=20,
    ).stdout
    assert (
        sum(
            min(subtitle_pixels[index : index + 3]) > 180
            for index in range(0, len(subtitle_pixels), 3)
        )
        > 10
    )
