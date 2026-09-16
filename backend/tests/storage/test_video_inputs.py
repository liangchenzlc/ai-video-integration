"""T10 offline admission, durable upload boundaries and observation coverage."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.video_inputs import UploadLifecycle, validate_video_parameters
from app.storage import capabilities
from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.settings import canonical
from tests.storage.production_fixtures import ProductionProject
from tests.storage.production_fixtures import production_project as production_project
from tests.storage.test_capabilities import profile
from tests.storage.test_drafts import opened as opened
from tests.storage.test_versions import adopt, candidate


def video_profile() -> dict:
    value = profile()
    value.update(
        stage="video",
        phases=["video"],
        enabled=True,
        accountState="available",
        qualityState="verified",
    )
    return value


@pytest.mark.parametrize("production_project", ["visible"], indirect=True)
def test_visible_dialogue_without_audio_path_blocks_without_submission(
    production_project: ProductionProject,
) -> None:
    project = production_project
    capability = video_profile()
    capabilities.initialize(project.service._application, [capability])
    result = project.service._production_audio.video_readiness(
        *project.args,
        {
            "shotRevisionId": project.shot_revision_id,
            "speechRevisionIds": [project.speech_revision_id],
            "capabilityId": capability["id"],
            "path": "research",
        },
    )
    assert result["ready"] is False
    assert "VISIBLE_DIALOGUE_UNSUPPORTED" in result["blockers"]
    assert "LOCAL_PREVIEW_CONFIRMATION_REQUIRED" in result["blockers"]
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        for table in ("service_calls", "uploads", "user_tasks", "cost_entries"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_audio_false_conflicts_with_actual_speech_before_preparation() -> None:
    capability = video_profile()
    capability["supportsAudioDrive"] = True
    with pytest.raises(ProjectError, match="AUDIO_PARAMETER_CONFLICT"):
        validate_video_parameters(capability, {"audio": False, "audioDrive": True}, has_speech=True)
    validate_video_parameters(capability, {"audio": True, "audioDrive": True}, has_speech=True)


def upload_options(project: ProductionProject, task_id: str, now: datetime) -> dict:
    return {
        "task_id": task_id,
        "media_id": project.media_id,
        "storage_profile_id": str(uuid4()),
        "object_key": "authorized-input.wav",
        "signed_until": (now + timedelta(hours=2)).isoformat(),
        "retain_until": (now + timedelta(days=1)).isoformat(),
        "processing_limit_seconds": 3600,
        "now": now,
    }


def authorized_journal_task(project: ProductionProject) -> str:
    """Persist the post-authorization fixture state without executing any adapter."""
    plan_id, task_id = str(uuid4()), str(uuid4())
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        media_hash = db.execute(
            "SELECT sha256 FROM media_files WHERE id=?", (project.media_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO task_plans VALUES(?,?,?,?,?,?,?,?)",
            (
                plan_id,
                project.shot_id,
                "video",
                canonical({"inputMediaHashes": [media_hash]}),
                "a" * 64,
                1,
                "2030-01-01T00:00:00+00:00",
                "real",
            ),
        )
        db.execute(
            "INSERT INTO user_tasks(id,plan_id,state,active,authorized_maximum_micro_cny) "
            "VALUES(?,?,'running',1,1)",
            (task_id, plan_id),
        )
    return task_id


def test_upload_cannot_be_registered_without_task_authorization(
    production_project: ProductionProject,
) -> None:
    project = production_project
    options = upload_options(project, str(uuid4()), datetime.now(UTC))
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        with pytest.raises(ProjectError, match="TASK_AUTHORIZATION_REQUIRED"):
            UploadLifecycle.register(db, **options)
        assert db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0


def test_live_and_unknown_uploads_survive_cleanup_then_deletion_is_retryable(
    production_project: ProductionProject,
) -> None:
    project = production_project
    now = datetime.now(UTC)
    task_id = authorized_journal_task(project)
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        upload_id = UploadLifecycle.register(db, **upload_options(project, task_id, now))
        digest = db.execute(
            "SELECT sha256 FROM media_files WHERE id=?", (project.media_id,)
        ).fetchone()[0]
        UploadLifecycle.complete(db, upload_id, digest)
    # Reopen to exercise persisted state rather than process-local upload flags.
    later = now + timedelta(days=2)
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        assert UploadLifecycle.mark_cleanup(db, later) == []
        db.execute("UPDATE user_tasks SET state='result_unknown',active=0 WHERE id=?", (task_id,))
        assert UploadLifecycle.mark_cleanup(db, later) == []
        db.execute("UPDATE user_tasks SET state='complete' WHERE id=?", (task_id,))
        assert [row["id"] for row in UploadLifecycle.mark_cleanup(db, later)] == [upload_id]
        UploadLifecycle.deletion_finished(db, upload_id, succeeded=False)
        assert (
            db.execute("SELECT state FROM uploads WHERE id=?", (upload_id,)).fetchone()[0]
            == "delete_pending"
        )
        UploadLifecycle.deletion_finished(db, upload_id, succeeded=True)
        assert (
            db.execute("SELECT state FROM uploads WHERE id=?", (upload_id,)).fetchone()[0]
            == "deleted"
        )


def test_upload_signature_must_cover_processing_limit(
    production_project: ProductionProject,
) -> None:
    project = production_project
    now = datetime.now(UTC)
    task_id = authorized_journal_task(project)
    options = upload_options(project, task_id, now)
    options["signed_until"] = (now + timedelta(seconds=3599)).isoformat()
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        with pytest.raises(ProjectError, match="UPLOAD_SIGNATURE_TOO_SHORT"):
            UploadLifecycle.register(db, **options)
        assert db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0


def test_ready_inputs_require_authorized_task_and_all_frozen_media(
    production_project: ProductionProject,
) -> None:
    project = production_project
    now = datetime.now(UTC)
    with connect(project.opened[1] / "project.sqlite3") as db:
        with pytest.raises(ProjectError, match="TASK_AUTHORIZATION_REQUIRED"):
            UploadLifecycle.require_available(db, str(uuid4()), 3600, now)
    task_id = authorized_journal_task(project)
    with connect(project.opened[1] / "project.sqlite3") as db, db:
        with pytest.raises(ProjectError, match="UPLOAD_INPUTS_INCOMPLETE"):
            UploadLifecycle.require_available(db, task_id, 3600, now)
        upload_id = UploadLifecycle.register(db, **upload_options(project, task_id, now))
        digest = db.execute(
            "SELECT sha256 FROM media_files WHERE id=?", (project.media_id,)
        ).fetchone()[0]
        UploadLifecycle.complete(db, upload_id, digest)
        assert [row["id"] for row in UploadLifecycle.require_available(db, task_id, 3600, now)] == [
            upload_id
        ]
        db.execute("UPDATE user_tasks SET active=0 WHERE id=?", (task_id,))
        with pytest.raises(ProjectError, match="TASK_AUTHORIZATION_REQUIRED"):
            UploadLifecycle.require_available(db, task_id, 3600, now)


def test_observation_cannot_claim_unwatched_or_problem_ranges_usable(
    production_project: ProductionProject,
) -> None:
    project = production_project
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        digest = db.execute(
            "SELECT sha256 FROM media_files WHERE id=?", (project.media_id,)
        ).fetchone()[0]
    content = {
        "mediaId": project.media_id,
        "mediaHash": digest,
        "method": "human",
        "observed": [{"startMs": 0, "endMs": 1000}],
        "usable": [{"startMs": 0, "endMs": 1001}],
        "problems": [],
        "limitations": "Only the first second was reviewed.",
    }
    with pytest.raises(ProjectError, match="OBSERVATION_NOT_COVERED"):
        candidate(project.opened, kind="observation", content=content)
    content["usable"][0]["endMs"] = 1000
    content["problems"] = [{"time": {"startMs": 900, "endMs": 1000}, "text": "听到杂音"}]
    with pytest.raises(ProjectError, match="OBSERVATION_CONFLICT"):
        candidate(project.opened, kind="observation", content=content)
    content["usable"][0]["endMs"] = 900
    artifact, revision = candidate(project.opened, kind="observation", content=content)
    adopt(project.opened, artifact, revision)
    assert project.service.get_artifact(*project.args, artifact)["adoptedRevisionId"] == revision
