"""Independent regressions for the first T04 backend review."""

from uuid import uuid4

import pytest
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_drafts import open_session, request, save
from tests.storage.test_projects import command, grant
from tests.storage.test_task_plans import budget, cmd, invoke, plan
from tests.tasks.test_executor import Counter, start, wait_task


def media(directory, mime, *, availability="available"):
    identifier = str(uuid4())
    with connect(directory / "project.sqlite3") as db, db:
        db.execute(
            "INSERT INTO media_files(id,relative_path,sha256,byte_length,mime,availability,"
            "provenance,source_json) VALUES(?,?,?,?,?,?,?,?)",
            (identifier, "media/" + identifier, "a" * 64, 1, mime, availability, "synthetic", "{}"),
        )
    return identifier


def plan_content(service, session, content, kind="observation", phase="check"):
    body = request(content, kind, cmd(service, session, {})["expectedRevision"])
    save(service, session, body)
    receipt = invoke(
        service,
        session,
        "plan_task",
        cmd(
            service,
            session,
            {
                "objectId": body["payload"]["artifactId"],
                "stage": phase.split("_")[0],
                "phase": phase,
                "goal": "Synthetic review fixture",
                "inputRevisionIds": [],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            },
        ),
    )
    return invoke(service, session, "get_task_plan", receipt["resourceId"])


@pytest.mark.parametrize("availability", [None, "missing", "staging", "quarantined"])
def test_check_rejects_missing_or_unavailable_top_level_media(opened, availability):
    service, directory, session = opened
    identifier = (
        str(uuid4())
        if availability is None
        else media(directory, "video/mp4", availability=availability)
    )
    with pytest.raises(ProjectError, match="MEDIA_MISSING"):
        plan_content(service, session, {"mediaId": identifier})


def test_check_rejects_declared_hash_mismatch(opened):
    service, directory, session = opened
    identifier = media(directory, "video/mp4")
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        plan_content(service, session, {"mediaId": identifier, "mediaHash": "b" * 64})


@pytest.mark.parametrize(
    "mime,disclosed", [("video/mp4", "video"), ("audio/wav", "audio"), ("image/png", "image")]
)
def test_check_freezes_hash_and_discloses_actual_media_type(opened, mime, disclosed):
    service, directory, session = opened
    identifier = media(directory, mime)
    frozen = plan_content(service, session, {"mediaId": identifier, "mediaHash": "a" * 64})
    assert frozen["inputMediaHashes"] == ["a" * 64]
    assert frozen["steps"][0]["disclosure"] == ["text", disclosed]
    assert frozen["inputPreview"]["payload"]["mediaId"] == identifier


@pytest.mark.parametrize("mutation", ["hash", "availability", "mime"])
def test_check_media_changes_stale_the_plan_before_any_submit(opened, mutation):
    service, directory, session = opened
    identifier = media(directory, "video/mp4")
    frozen = plan_content(service, session, {"mediaId": identifier})
    with connect(directory / "project.sqlite3") as db, db:
        sql, value = {
            "hash": ("UPDATE media_files SET sha256=? WHERE id=?", "b" * 64),
            "availability": ("UPDATE media_files SET availability=? WHERE id=?", "missing"),
            "mime": ("UPDATE media_files SET mime=? WHERE id=?", "audio/wav"),
        }[mutation]
        db.execute(sql, (value, identifier))
    with pytest.raises(ProjectError, match="PLAN_STALE"):
        start(service, session, frozen)
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0


@pytest.mark.parametrize("mime,disclosed", [("audio/wav", "audio"), ("video/mp4", "video")])
def test_reference_disclosure_uses_actual_mime(opened, mime, disclosed):
    service, directory, session = opened
    identifier = media(directory, mime)
    frozen = plan_content(
        service,
        session,
        {
            "purpose": "shot",
            "startState": "before",
            "endState": "after",
            "plannedMs": 4000,
            "references": [{"mediaId": identifier, "mediaHash": "a" * 64, "role": "voiceDrive"}],
        },
        "shot",
        "video",
    )
    assert frozen["steps"][0]["disclosure"] == ["text", disclosed]


@pytest.mark.parametrize(
    "kind,phase,content,key,mime",
    [
        ("speech", "speech", {"text": "Synthetic speech"}, "mediaId", "audio/wav"),
        (
            "shot",
            "video",
            {"purpose": "shot", "startState": "a", "endState": "b", "plannedMs": 4000},
            "videoMediaId",
            "video/mp4",
        ),
    ],
)
def test_other_stage_top_level_media_inputs_are_frozen(opened, kind, phase, content, key, mime):
    service, directory, session = opened
    identifier = media(directory, mime)
    frozen = plan_content(service, session, {**content, key: identifier}, kind, phase)
    assert frozen["inputMediaHashes"] == ["a" * 64]
    assert frozen["steps"][0]["disclosure"] == ["text", mime.split("/")[0]]


def unknown_task(service, session):
    service._tasks.adapter = Counter(lost=True)
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    assert wait_task(service, session, receipt["resourceId"])["state"] == "result_unknown"
    service._tasks.executor.thread.join(timeout=3)
    return receipt["resourceId"]


@pytest.mark.parametrize("change", ["moved", "replaced"])
def test_unavailable_retained_project_does_not_hide_healthy_activity(opened, tmp_path, change):
    service, directory, session = opened
    task_id = unknown_task(service, session)
    service.close_session(session["projectSessionId"], 1)
    second_dir = tmp_path / "healthy"
    second_dir.mkdir()
    service.create_project(command(grant(service, second_dir, "createProject")), 1)
    healthy = open_session(service, second_dir)
    healthy_task = unknown_task(service, healthy)
    if change == "moved":
        moved = tmp_path / "relocated"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        assert moved.resolve().is_relative_to(tmp_path.resolve())
        directory.rename(moved)
    else:
        with connect(directory / "project.sqlite3") as db, db:
            db.execute("UPDATE projects SET id=?", (str(uuid4()),))
    assert service.get_task_activity() == [
        {
            "projectId": healthy["projectId"],
            "projectName": "A project",
            "taskId": healthy_task,
            "state": "result_unknown",
        }
    ]
    if change == "moved":
        reopened = open_session(service, moved)
        assert reopened["projectId"] == session["projectId"]
        assert {item["taskId"] for item in service.get_task_activity()} == {task_id, healthy_task}
