"""B11 local rights evidence and ordinary, reviewable mix keyframes."""

import copy
import hashlib
import sqlite3
from uuid import uuid4

import pytest

from app.storage import production_audio, revisions, timeline
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.production_fixtures import ProductionProject
from tests.storage.production_fixtures import production_project as production_project
from tests.storage.test_drafts import opened as opened
from tests.storage.test_production_timeline import clip
from tests.storage.test_versions import adopt, candidate, command, current


def evidence_media(project: ProductionProject) -> str:
    identifier = str(uuid4())
    path = project.audio_path.parent / (identifier + ".wav")
    path.write_bytes(project.audio_path.read_bytes())
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        db.execute(
            "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                "media/" + path.name,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_size,
                "audio/wav",
                5200,
                None,
                None,
                "available",
                "imported",
                "{}",
            ),
        )
    return identifier


def rights_payload(project: ProductionProject, evidence_id: str) -> dict:
    return {
        "id": str(uuid4()),
        "mediaId": project.media_id,
        "source": "本地录音工程样例",
        "use": "仅离线工程测试",
        "evidenceMediaIds": [evidence_id],
        "state": "verified",
        "explanation": "人工核对样例来源记录；不声明已通过法律审查。",
    }


def save_rights(project: ProductionProject, evidence: dict) -> dict:
    return project.service._production_audio.save_rights(
        *project.args,
        evidence["id"],
        command(current(project.opened), {"evidence": evidence}),
    )


def test_verified_rights_require_reason_evidence_and_matching_route_id(
    production_project: ProductionProject,
) -> None:
    project = production_project
    evidence = rights_payload(project, evidence_media(project))
    missing = copy.deepcopy(evidence)
    missing["evidenceMediaIds"] = []
    with pytest.raises(ProjectError, match="RIGHTS_VERIFICATION_REQUIRED"):
        save_rights(project, missing)
    missing = copy.deepcopy(evidence)
    missing["explanation"] = " "
    with pytest.raises(ProjectError, match="RIGHTS_VERIFICATION_REQUIRED"):
        save_rights(project, missing)
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        project.service._production_audio.save_rights(
            *project.args,
            str(uuid4()),
            command(current(project.opened), {"evidence": evidence}),
        )
    save_rights(project, evidence)
    assert project.service._production_audio.list_rights(*project.args)["items"] == [evidence]
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        assert production_audio.rights_verified(db, project.media_id)
        assert db.execute("SELECT count(*) FROM rights_verifications").fetchone()[0] == 1


def test_replaced_rights_evidence_hash_invalidates_prior_verification(
    production_project: ProductionProject,
) -> None:
    project = production_project
    evidence_id = evidence_media(project)
    save_rights(project, rights_payload(project, evidence_id))
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        assert production_audio.rights_verified(db, project.media_id)
        path = project.audio_path.parent / (evidence_id + ".wav")
        original_bytes = path.read_bytes()
        path.write_bytes(original_bytes + b"externally changed")
        assert not production_audio.rights_verified(db, project.media_id)
        path.write_bytes(original_bytes)
        assert production_audio.rights_verified(db, project.media_id)
        db.execute("UPDATE media_files SET sha256=? WHERE id=?", ("a" * 64, evidence_id))
        assert not production_audio.rights_verified(db, project.media_id)
        assert db.execute("SELECT count(*) FROM rights_verifications").fetchone()[0] == 1


def mixed_timeline(
    project: ProductionProject, *, mute_voice: bool = False
) -> tuple[str, str, dict]:
    voice_track, music_track = str(uuid4()), str(uuid4())
    voice = clip(
        voice_track,
        None,
        0,
        5200,
        contentRevisionId=project.speech_revision_id,
        shotId=project.shot_id,
    )
    music = clip(music_track, project.media_id, 0, 5200)
    content = {
        "width": 1280,
        "height": 720,
        "fps": {"numerator": 24, "denominator": 1},
        "durationMs": 5200,
        "burnSubtitles": False,
        "tracks": [
            {"id": voice_track, "kind": "voice", "order": 0, "muted": mute_voice},
            {"id": music_track, "kind": "music", "order": 1, "muted": False},
        ],
        "clips": [voice, music],
        "transitions": [],
    }
    artifact, revision = candidate(project.opened, kind="timeline", content=content)
    adopt(project.opened, artifact, revision)
    return artifact, revision, content


def test_ducking_uses_actual_voiced_ranges_and_preserves_adopted_revision(
    production_project: ProductionProject,
) -> None:
    project = production_project
    artifact, revision, original = mixed_timeline(project)
    result = project.service._production_audio.ducking(
        *project.args,
        {
            "timelineRevisionId": revision,
            "musicClipIds": [original["clips"][1]["id"]],
            "reductionDb": 12,
            "attackMs": 100,
            "releaseMs": 100,
        },
    )
    points = result["timeline"]["clips"][1]["keyframes"]
    low = 10 ** (-12 / 20)
    assert timeline.value_at(points, "volume", 1000, 1) == pytest.approx(low)
    assert timeline.value_at(points, "volume", 2250, 1) == pytest.approx(1)
    assert timeline.value_at(points, "volume", 3000, 1) == pytest.approx(low)
    assert low < timeline.value_at(points, "volume", 2050, 1) < 1
    assert low < timeline.value_at(points, "volume", 2450, 1) < 1
    assert any(warning.startswith("DUPLICATE_AUDIO:") for warning in result["warnings"])
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        assert revisions.get(db, revision)["payload"]["content"] == original
        assert revisions.artifact(db, artifact)["adoptedRevisionId"] == revision
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0


def test_muted_voice_does_not_create_hidden_ducking(production_project: ProductionProject) -> None:
    project = production_project
    _, revision, original = mixed_timeline(project, mute_voice=True)
    result = project.service._production_audio.ducking(
        *project.args,
        {
            "timelineRevisionId": revision,
            "musicClipIds": [original["clips"][1]["id"]],
            "reductionDb": 12,
            "attackMs": 100,
            "releaseMs": 100,
        },
    )
    assert result["timeline"] == original
    for muted_clip in (
        {"gainDb": -96},
        {"keyframes": [{"timeMs": 0, "property": "volume", "value": 0, "interpolation": "hold"}]},
    ):
        content = copy.deepcopy(original)
        content["tracks"][0]["muted"] = False
        content["clips"][0].update(muted_clip)
        artifact, revision = candidate(project.opened, kind="timeline", content=content)
        adopt(project.opened, artifact, revision)
        result = project.service._production_audio.ducking(
            *project.args,
            {
                "timelineRevisionId": revision,
                "musicClipIds": [content["clips"][1]["id"]],
                "reductionDb": 12,
                "attackMs": 100,
                "releaseMs": 100,
            },
        )
        assert result["timeline"] == content
        assert not any(warning.startswith("DUPLICATE_AUDIO:") for warning in result["warnings"])


def test_readonly_schema7_rights_reports_upgrade_before_querying_missing_tables() -> None:
    with sqlite3.connect(":memory:") as db:
        db.execute("PRAGMA user_version=7")
        db.execute("PRAGMA query_only=1")
        with pytest.raises(ProjectError, match="PROJECT_UPGRADE_REQUIRED") as raised:
            production_audio.list_rights(db)
        assert raised.value.status_code == 409
