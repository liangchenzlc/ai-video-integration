"""B12: current evidence gates and a short real frozen local MP4 delivery."""

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.storage import checks, issues, production_audio_checks, revisions
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.production_fixtures import ProductionProject
from tests.storage.production_fixtures import production_project as production_project
from tests.storage.test_drafts import opened as opened
from tests.storage.test_media import FFMPEG, configure, wait_job
from tests.storage.test_production_mix import evidence_media, rights_payload, save_rights
from tests.storage.test_production_timeline import basic_timeline, clip, register_media
from tests.storage.test_projects import grant
from tests.storage.test_versions import adopt, candidate, command, current

Json = dict[str, Any]
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="Repository FFmpeg unavailable")


def check(project: ProductionProject, revision: str, rules: list[str]) -> Json:
    receipt = project.service.run_local_checks(
        *project.args,
        command(current(project.opened), {"revisionIds": [revision], "ruleIds": rules}),
    )
    job = project.service.get_job(*project.args, receipt["resourceId"])
    return project.service.get_check_report(*project.args, job["resultId"])


def eligible(project: ProductionProject) -> tuple[str, str, Json]:
    configure(project.service)
    image = register_media(project, "delivery.png", "green", None)
    evidence = rights_payload(project, evidence_media(project))
    evidence["mediaId"] = image
    save_rights(project, evidence)
    content = basic_timeline()
    content["tracks"] = content["tracks"][:1]
    content["clips"] = [clip(content["tracks"][0]["id"], image, 0, 500)]
    content["durationMs"] = 500
    artifact, revision = candidate(project.opened, kind="timeline", content=content)
    adopt(project.opened, artifact, revision)
    report = check(project, revision, checks.RULES)
    assert report["outcome"] == "pass", report
    project.service.confirm_revision(
        *project.args,
        artifact,
        command(current(project.opened), {"revisionId": revision, "checkIds": [report["id"]]}),
    )
    return artifact, revision, content


def export_command(
    project: ProductionProject,
    revision: str,
    path: Path,
    *,
    overwrite: bool = False,
    burn: bool = True,
) -> Json:
    return command(
        current(project.opened),
        {
            "timelineRevisionId": revision,
            "targetGrantId": grant(project.service, path, "exportFilm"),
            "burnSubtitles": burn,
            "overwriteConfirmed": overwrite,
        },
    )


def export_job(project: ProductionProject, export_id: str) -> tuple[Json, Json]:
    record = project.service._rendering.get_export(*project.args, export_id)
    job = wait_job(project.service, project.args, {"resourceId": record["jobId"]})
    return project.service._rendering.get_export(*project.args, export_id), job


def test_blocking_issue_cannot_be_accepted_as_deviation(
    production_project: ProductionProject,
) -> None:
    project = production_project
    _, revision, content = eligible(project)
    missing = content["clips"][0]["mediaId"]
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        db.execute("UPDATE media_files SET availability='missing' WHERE id=?", (missing,))
    report = check(project, revision, ["media.available"])
    assert report["outcome"] == "fail"
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        issue = report["issueIds"][0]
        with pytest.raises(ProjectError, match="CHECK_BLOCKED"):
            issues.decide(
                db,
                issue,
                {"action": "accept_deviation", "reason": "不能接受阻断", "evidenceMediaIds": []},
                str(uuid4()),
            )
        assert db.execute("SELECT status FROM checks WHERE id=?", (issue,)).fetchone()[0] == "open"
        assert db.execute("SELECT count(*) FROM check_decisions").fetchone()[0] == 0


@pytest.mark.parametrize("fault", ["muted", "source", "outside"])
def test_dialogue_requires_actual_audible_source_inside_shot(
    production_project: ProductionProject,
    fault: str,
) -> None:
    project = production_project
    image = register_media(project, "dialogue.png", "red", None)
    content = basic_timeline()
    content["tracks"] = content["tracks"][:2]
    content["durationMs"] = 6500
    content["clips"] = [
        clip(content["tracks"][0]["id"], image, 0, 5200, shotId=project.shot_id),
        clip(
            content["tracks"][1]["id"],
            None,
            0,
            5200,
            contentRevisionId=project.speech_revision_id,
            shotId=project.shot_id,
        ),
    ]
    _, revision = candidate(project.opened, kind="timeline", content=content)
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        target = revisions.get(db, revision)
        assert production_audio_checks.evaluate(db, target, "dialogue.timing")["outcome"] == "pass"
        if fault == "muted":
            target["payload"]["content"]["tracks"][1]["muted"] = True
        elif fault == "source":
            target["payload"]["content"]["clips"][1]["mediaId"] = image
        else:
            target["payload"]["content"]["clips"][1]["startMs"] = 1000
        result = production_audio_checks.evaluate(db, target, "dialogue.timing")
    assert result["outcome"] == "fail"
    expected = {
        "muted": "DIALOGUE_MAPPING_UNKNOWN",
        "source": "SPEECH_MEDIA_MISMATCH",
        "outside": "SPEECH_OUTSIDE_SHOT",
    }[fault]
    assert expected in {finding["message"] for finding in result["issues"]}


def test_muted_required_visual_carrier_cannot_reuse_human_observation(
    production_project: ProductionProject,
) -> None:
    project = production_project
    media_id = register_media(project, "required.mp4", "blue", 1000)
    required_id, scene_id, shot_id = (str(uuid4()) for _ in range(3))
    story, story_revision = candidate(
        project.opened,
        content={
            "sourceText": "蓝色画面",
            "brief": "保留",
            "inputType": "script",
            "requirements": [
                {
                    "id": required_id,
                    "text": "蓝色画面",
                    "category": "fact",
                    "source": None,
                    "required": True,
                    "decision": "keep",
                    "decisionReason": "",
                }
            ],
            "scenes": [
                {
                    "id": scene_id,
                    "title": "蓝色",
                    "action": "显示",
                    "plannedMs": 1000,
                    "locationAssetId": None,
                }
            ],
        },
    )
    adopt(project.opened, story, story_revision)
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        source = revisions.get(db, project.shot_revision_id)["payload"]["content"]
        digest = db.execute("SELECT sha256 FROM media_files WHERE id=?", (media_id,)).fetchone()[0]
    source.update(
        shotId=shot_id,
        sceneId=scene_id,
        plannedMs=1000,
        dialogueIds=[],
        requirementIds=[required_id],
        assetRevisionIds=[],
        videoMediaId=media_id,
        events=[
            {
                "id": str(uuid4()),
                "text": "蓝色画面",
                "time": {"startMs": 0, "endMs": 500},
                "requirementIds": [required_id],
                "carrier": "visual",
                "observer": "audience",
            }
        ],
    )
    shot, shot_revision = candidate(project.opened, kind="shot", content=source)
    adopt(project.opened, shot, shot_revision)
    observation, observed = candidate(
        project.opened,
        kind="observation",
        content={
            "mediaId": media_id,
            "mediaHash": digest,
            "method": "human",
            "observed": [{"startMs": 0, "endMs": 1000}],
            "usable": [{"startMs": 0, "endMs": 1000}],
            "problems": [],
            "limitations": "仅测试人工观察记录边界",
        },
    )
    adopt(project.opened, observation, observed)
    content = basic_timeline()
    content["tracks"] = [dict(content["tracks"][0], kind="video")]
    content["clips"] = [clip(content["tracks"][0]["id"], media_id, 0, 1000, shotId=shot_id)]
    content["durationMs"] = 1000
    _, revision = candidate(project.opened, kind="timeline", content=content)
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        target = revisions.get(db, revision)
        assert (
            production_audio_checks.evaluate(db, target, "requirement.coverage")["outcome"]
            == "pass"
        )
        target["payload"]["content"]["tracks"][0]["muted"] = True
        result = production_audio_checks.evaluate(db, target, "requirement.coverage")
    assert result["outcome"] == "fail"
    assert result["issues"][0]["message"] == "REQUIREMENT_CARRIER_TRIMMED"


def test_export_reevaluates_effective_subtitle_switch(
    production_project: ProductionProject,
    tmp_path: Path,
) -> None:
    project = production_project
    configure(project.service)
    media_id = register_media(project, "caption-background.mp4", "blue", 500)
    proof = rights_payload(project, evidence_media(project))
    proof["mediaId"] = media_id
    save_rights(project, proof)
    requirement_id, scene_id, shot_id = (str(uuid4()) for _ in range(3))
    story, story_revision = candidate(
        project.opened,
        content={
            "sourceText": "必须出现",
            "brief": "字幕承载",
            "inputType": "script",
            "requirements": [
                {
                    "id": requirement_id,
                    "text": "必须出现",
                    "category": "screenText",
                    "source": None,
                    "required": True,
                    "decision": "keep",
                    "decisionReason": "",
                }
            ],
            "scenes": [
                {
                    "id": scene_id,
                    "title": "字幕",
                    "action": "显示",
                    "plannedMs": 500,
                    "locationAssetId": None,
                }
            ],
        },
    )
    adopt(project.opened, story, story_revision)
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        shot_content = revisions.get(db, project.shot_revision_id)["payload"]["content"]
    shot_content.update(
        shotId=shot_id,
        sceneId=scene_id,
        plannedMs=500,
        dialogueIds=[],
        requirementIds=[requirement_id],
        assetRevisionIds=[],
        videoMediaId=media_id,
        events=[
            {
                "id": str(uuid4()),
                "text": "必须出现",
                "time": {"startMs": 0, "endMs": 500},
                "requirementIds": [requirement_id],
                "carrier": "subtitle",
                "observer": "audience",
            }
        ],
    )
    shot, shot_revision = candidate(project.opened, kind="shot", content=shot_content)
    adopt(project.opened, shot, shot_revision)
    subtitle, subtitle_revision = candidate(
        project.opened,
        kind="subtitle",
        content={
            "audioRevisionId": None,
            "timingMethod": "manual",
            "cues": [
                {
                    "id": str(uuid4()),
                    "dialogueId": None,
                    "text": "必须出现",
                    "time": {"startMs": 0, "endMs": 500},
                    "differsFromDialogue": False,
                }
            ],
        },
    )
    adopt(project.opened, subtitle, subtitle_revision)
    content = basic_timeline()
    content["tracks"] = [dict(content["tracks"][0], kind="video"), content["tracks"][2]]
    content["clips"] = [
        clip(content["tracks"][0]["id"], media_id, 0, 500, shotId=shot_id),
        clip(
            content["tracks"][1]["id"],
            None,
            0,
            500,
            shotId=shot_id,
            contentRevisionId=subtitle_revision,
        ),
    ]
    content["durationMs"] = 500
    artifact, revision = candidate(project.opened, kind="timeline", content=content)
    adopt(project.opened, artifact, revision)
    assert check(project, revision, ["requirement.coverage"])["outcome"] == "unknown"
    receipt = project.service._rendering.render_animatic(
        *project.args, command(current(project.opened), {"timelineRevisionId": revision})
    )
    animatic = wait_job(project.service, project.args, receipt)
    assert animatic["state"] == "succeeded", json.dumps(animatic)
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        row = db.execute(
            "SELECT sha256 FROM media_files WHERE id=?", (animatic["resultId"],)
        ).fetchone()
    observation, observation_revision = candidate(
        project.opened,
        kind="observation",
        content={
            "mediaId": animatic["resultId"],
            "mediaHash": row[0],
            "method": "human",
            "observed": [{"startMs": 0, "endMs": 500}],
            "usable": [{"startMs": 0, "endMs": 500}],
            "problems": [],
            "limitations": "工程测试人工观察记录，不代表作品艺术验收",
        },
    )
    adopt(project.opened, observation, observation_revision)
    for item_artifact, item_revision in [
        (story, story_revision),
        (shot, shot_revision),
        (subtitle, subtitle_revision),
        (artifact, revision),
    ]:
        base_report = check(project, item_revision, checks.BASE_RULES)
        assert base_report["outcome"] == "pass", base_report
        project.service.confirm_revision(
            *project.args,
            item_artifact,
            command(
                current(project.opened),
                {"revisionId": item_revision, "checkIds": [base_report["id"]]},
            ),
        )
    final_report = check(project, revision, checks.PRODUCTION_RULES)
    assert final_report["outcome"] == "pass", final_report
    with pytest.raises(ProjectError, match="CHECK_BLOCKED"):
        project.service._rendering.export_film(
            *project.args, export_command(project, revision, tmp_path / "disabled.mp4", burn=False)
        )
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM exports").fetchone()[0] == 0
        assert revisions.get(db, revision)["payload"]["content"]["burnSubtitles"] is True
    exported = project.service._rendering.export_film(
        *project.args, export_command(project, revision, tmp_path / "enabled.mp4", burn=True)
    )
    record, job = export_job(project, exported["resourceId"])
    assert job["state"] == "succeeded" and record["state"] == "complete", json.dumps(job)


def test_real_export_is_frozen_idempotent_and_ignores_abandoned_candidate_issue(
    production_project: ProductionProject,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = production_project
    artifact, revision, content = eligible(project)
    abandoned_media = register_media(project, "abandoned.png", "red", None)
    abandoned = copy.deepcopy(content)
    abandoned["clips"][0]["mediaId"] = abandoned_media
    _, abandoned_revision = candidate(project.opened, kind="timeline", content=abandoned)
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        db.execute("UPDATE media_files SET availability='missing' WHERE id=?", (abandoned_media,))
    assert check(project, abandoned_revision, ["media.available"])["outcome"] == "fail"
    target = tmp_path / "完整成片.mp4"
    body = export_command(project, revision, target)
    renderer = project.service._rendering
    queued: list[tuple[Path, str, str]] = []
    real_enqueue = renderer.enqueue
    monkeypatch.setattr(renderer, "enqueue", lambda *args: queued.append(args))
    receipt = renderer.export_film(*project.args, body)
    assert renderer.export_film(*project.args, body) == receipt
    assert len(queued) == 1
    updated = copy.deepcopy(content)
    updated["burnSubtitles"] = False
    _, later = candidate(
        project.opened, artifact=artifact, kind="timeline", content=updated, parent=revision
    )
    adopt(project.opened, artifact, later)
    real_enqueue(*queued[0])
    record, job = export_job(project, receipt["resourceId"])
    assert job["state"] == "succeeded", json.dumps(job)
    assert record["state"] == "complete" and record["timelineRevisionId"] == revision
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        row = db.execute("SELECT * FROM media_files WHERE id=?", (record["mediaId"],)).fetchone()
        assert db.execute("SELECT count(*) FROM exports").fetchone()[0] == 1
        assert revisions.artifact(db, artifact)["adoptedRevisionId"] == later
        frozen = json.loads(db.execute("SELECT plan_json FROM render_plans").fetchone()[0])
        assert frozen["timeline"]["burnSubtitles"] is True
    assert target.read_bytes() == (project.opened[1] / row["relative_path"]).read_bytes()
    assert hashlib.sha256(target.read_bytes()).hexdigest() == row["sha256"]
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-xerror", "-i", str(target), "-f", "null", "-"],
        check=True,
        capture_output=True,
        timeout=20,
    )


def test_failed_external_delivery_preserves_canonical_output_and_old_target(
    production_project: ProductionProject,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = production_project
    _, revision, _ = eligible(project)
    target = tmp_path / "existing.mp4"
    target.write_bytes(b"original external target")

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise OSError("Injected unavailable delivery volume")

    monkeypatch.setattr(project.service._rendering, "_publish", unavailable)
    receipt = project.service._rendering.export_film(
        *project.args, export_command(project, revision, target, overwrite=True)
    )
    record, job = export_job(project, receipt["resourceId"])
    assert job["state"] == "failed" and record["state"] == "failed"
    assert target.read_bytes() == b"original external target"
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        row = db.execute("SELECT * FROM media_files WHERE id=?", (record["mediaId"],)).fetchone()
    internal = project.opened[1] / row["relative_path"]
    assert internal.is_file() and row["availability"] == "available"
    assert hashlib.sha256(internal.read_bytes()).hexdigest() == row["sha256"]
