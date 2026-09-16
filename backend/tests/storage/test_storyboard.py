"""Basic T07 storyboard behavior through durable project sessions."""

import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage import storyboard
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_drafts import request, save
from tests.storage.test_projects import command, grant
from tests.storage.test_versions import adopt, candidate


@pytest.fixture
def project_fixture(tmp_path: Path) -> Iterator[tuple[ProjectService, Path, dict]]:
    directory = tmp_path / "project"
    directory.mkdir()
    service = ProjectService(tmp_path / "app")
    service.create_project(command(grant(service, directory, "createProject")), 1)
    from tests.storage.test_drafts import open_session

    session = open_session(service, directory)
    yield service, directory, session
    service.close()


def mutate(service: ProjectService, session: dict, action: str, payload: dict) -> dict:
    args = (session["projectId"], session["projectSessionId"], 1)
    revision = service.get_project(*args)["revision"]
    command = {
        "clientOperationId": str(uuid4()),
        "expectedRevision": revision,
        "payload": payload,
    }
    return getattr(service, action)(*args, command)


def test_shot_index_stable_across_draft_edits_and_reopen(project_fixture: tuple) -> None:
    service, directory, session = project_fixture
    shot_id = str(uuid4())
    body = request({"shotId": shot_id, "purpose": "First"}, "shot")
    save(service, session, body)
    body["clientOperationId"] = str(uuid4())
    body["expectedRevision"] = 2
    body["payload"]["content"]["content"]["purpose"] = "Edited"
    save(service, session, body)
    args = (session["projectId"], session["projectSessionId"], 1)
    assert service.get_storyboard(*args)["shotIds"] == [shot_id]
    assert service.get_storyboard(*args)["drafts"][0]["id"] == body["payload"]["draftId"]
    service.close()
    from tests.storage.test_drafts import open_session

    restarted = ProjectService(service.app_data_dir)
    try:
        new_session = open_session(restarted, directory)
        assert restarted.get_storyboard(
            new_session["projectId"], new_session["projectSessionId"], 1
        )["shotIds"] == [shot_id]
    finally:
        restarted.close()


def test_shot_identity_collision_rejected_without_revision(project_fixture: tuple) -> None:
    service, _, session = project_fixture
    shot_id = str(uuid4())
    save(service, session, request({"shotId": shot_id}, "shot"))
    args = (session["projectId"], session["projectSessionId"], 1)
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        save(service, session, request({"shotId": shot_id}, "shot", revision=2))
    assert service.get_project(*args)["revision"] == 2


def test_reorder_is_atomic_and_replayable(project_fixture: tuple) -> None:
    service, _, session = project_fixture
    ids = [str(uuid4()) for _ in range(3)]
    for revision, shot_id in enumerate(ids, start=1):
        save(service, session, request({"shotId": shot_id}, "shot", revision))
    args = (session["projectId"], session["projectSessionId"], 1)
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        mutate(service, session, "reorder_shots", {"shotIds": [ids[0], ids[0], ids[2]]})
    receipt = mutate(service, session, "reorder_shots", {"shotIds": ids[::-1]})
    assert receipt["committedRevision"] == 5
    assert service.get_storyboard(*args)["shotIds"] == ids[::-1]
    assert service.get_project(*args)["revision"] == 5


def test_reorder_rejects_active_task_with_adopted_timeline_input(project_fixture: tuple) -> None:
    service, directory, session = project_fixture
    shot_ids = [str(uuid4()), str(uuid4())]
    for revision, shot_id in enumerate(shot_ids, 1):
        save(service, session, request({"shotId": shot_id}, "shot", revision))
    timeline_id, revision_id, plan_id, task_id = (str(uuid4()) for _ in range(4))
    with connect(directory / "project.sqlite3") as db, db:
        db.execute("INSERT INTO artifacts(id,kind) VALUES(?,'timeline')", (timeline_id,))
        db.execute(
            "INSERT INTO revisions VALUES(?,?,?,?,?,?)",
            (
                revision_id,
                timeline_id,
                None,
                '{"kind":"timeline","content":{}}',
                "a" * 64,
                "2026-09-16T00:00:00+00:00",
            ),
        )
        db.execute(
            "UPDATE artifacts SET adopted_revision_id=? WHERE id=?", (revision_id, timeline_id)
        )
        db.execute(
            "INSERT INTO task_plans VALUES(?,?,?,?,?,?,?,?)",
            (
                plan_id,
                timeline_id,
                "video",
                "{}",
                "a" * 64,
                0,
                "2026-09-17T00:00:00+00:00",
                "synthetic",
            ),
        )
        db.execute(
            "INSERT INTO user_tasks(id,plan_id,state,active,authorized_maximum_micro_cny) "
            "VALUES(?,?,'running',1,0)",
            (task_id, plan_id),
        )
        db.execute("INSERT INTO task_inputs VALUES(?,?)", (task_id, revision_id))
    args = (session["projectId"], session["projectSessionId"], 1)
    before = service.get_project(*args)["revision"]
    with pytest.raises(ProjectError, match="INPUT_LOCKED"):
        mutate(service, session, "reorder_shots", {"shotIds": shot_ids[::-1]})
    assert service.get_storyboard(*args)["shotIds"] == shot_ids
    assert service.get_project(*args)["revision"] == before


def test_coverage_retains_required_unseen_event(project_fixture: tuple) -> None:
    service, _, session = project_fixture
    requirement_id = str(uuid4())
    source = "甲😀松手"
    save(
        service,
        session,
        request(
            {
                "sourceText": source,
                "requirements": [
                    {
                        "id": requirement_id,
                        "text": "松手",
                        "required": True,
                        "decision": "keep",
                        "source": {
                            "sourceHash": hashlib.sha256(source.encode()).hexdigest(),
                            "startCodePoint": 2,
                            "endCodePoint": 4,
                        },
                    }
                ],
            }
        ),
    )
    args = (session["projectId"], session["projectSessionId"], 1)
    # Drafts are not adopted facts and cannot discharge the requirement.
    assert service.get_coverage(*args)["unassignedRequirementIds"] == []


def test_adopted_story_reports_unseen_required_event_and_stale_source(
    project_fixture: tuple,
) -> None:
    service, directory, session = project_fixture
    requirement_id = str(uuid4())
    source = "甲😀松手"
    artifact, revision = candidate(
        project_fixture,
        kind="story",
        content={
            "sourceText": source,
            "brief": "Keep the action",
            "inputType": "script",
            "requirements": [
                {
                    "id": requirement_id,
                    "text": "松手",
                    "category": "action",
                    "required": True,
                    "decision": "keep",
                    "decisionReason": "",
                    "source": {
                        "sourceHash": "b" * 64,
                        "startCodePoint": 2,
                        "endCodePoint": 4,
                    },
                }
            ],
        },
    )
    adopt(project_fixture, artifact, revision)
    result = service.get_coverage(session["projectId"], session["projectSessionId"], 1)
    assert result["unassignedRequirementIds"] == [requirement_id]
    assert result["unresolvedRequirementIds"] == [requirement_id]
    args = (session["projectId"], session["projectSessionId"], 1)
    service.run_local_checks(
        *args,
        {
            "clientOperationId": str(uuid4()),
            "expectedRevision": service.get_project(*args)["revision"],
            "payload": {"revisionIds": [revision], "ruleIds": ["structural"]},
        },
    )
    with connect(directory / "project.sqlite3", "ro") as db:
        outcome = db.execute("SELECT outcome FROM check_runs ORDER BY rowid DESC LIMIT 1")
        assert outcome.fetchone()[0] == "fail"
    with pytest.raises(ProjectError, match="CHECK_REQUIRED"):
        service.confirm_revision(
            *args,
            artifact,
            {
                "clientOperationId": str(uuid4()),
                "expectedRevision": service.get_project(*args)["revision"],
                "payload": {"revisionId": revision, "checkIds": []},
            },
        )


def test_reorder_preserves_requirement_gap_when_adopted_shot_becomes_stale(
    project_fixture: tuple,
) -> None:
    service, _, session = project_fixture
    args = (session["projectId"], session["projectSessionId"], 1)
    requirement_id, scene_id = str(uuid4()), str(uuid4())
    story, story_revision = candidate(
        project_fixture,
        content={
            "sourceText": "release",
            "brief": "Release",
            "inputType": "script",
            "requirements": [
                {
                    "id": requirement_id,
                    "text": "release",
                    "category": "action",
                    "source": None,
                    "required": True,
                    "decision": "keep",
                    "decisionReason": "",
                }
            ],
            "scenes": [
                {
                    "id": scene_id,
                    "title": "A",
                    "action": "Release",
                    "plannedMs": 1000,
                    "locationAssetId": None,
                }
            ],
        },
    )
    adopt(project_fixture, story, story_revision)
    shot_id = str(uuid4())
    body = request(
        {
            "shotId": shot_id,
            "purpose": "Show the hand",
            "sceneId": scene_id,
            "assetRevisionIds": [],
            "requirementIds": [requirement_id],
            "startState": "holding",
            "events": [
                {
                    "id": str(uuid4()),
                    "text": "releases",
                    "time": {"startMs": 0, "endMs": 500},
                    "requirementIds": [requirement_id],
                    "carrier": "visual",
                    "observer": "audience",
                }
            ],
            "endState": "released",
            "camera": "close",
            "subjectHand": "right",
            "plannedMs": 1000,
            "dialogueIds": [],
            "references": [],
            "videoMediaId": None,
            "pickupOfShotId": None,
            "use": "original",
        },
        "shot",
        service.get_project(*args)["revision"],
    )
    save(service, session, body)
    shot_artifact = body["payload"]["artifactId"]
    shot_revision = service.create_revision(
        *args,
        shot_artifact,
        {
            "clientOperationId": str(uuid4()),
            "expectedRevision": service.get_project(*args)["revision"],
            "payload": {"draftId": body["payload"]["draftId"]},
        },
    )["resourceId"]
    adopt(project_fixture, shot_artifact, shot_revision)
    assert service.get_coverage(*args)["unassignedRequirementIds"] == []
    second_id = str(uuid4())
    save(
        service,
        session,
        request({"shotId": second_id}, "shot", service.get_project(*args)["revision"]),
    )
    mutate(service, session, "reorder_shots", {"shotIds": [second_id, shot_id]})
    assert service.get_coverage(*args)["unassignedRequirementIds"] == [requirement_id]


@pytest.mark.parametrize("invalid", ["out_of_range_event", "unbound_event", "self_pickup"])
def test_formal_shot_rejects_invalid_event_or_pickup(project_fixture: tuple, invalid: str) -> None:
    service, directory, session = project_fixture
    shot_id, requirement_id = str(uuid4()), str(uuid4())
    save(service, session, request({"shotId": shot_id}, "shot"))
    content = {
        "shotId": shot_id,
        "plannedMs": 1000,
        "requirementIds": [requirement_id],
        "events": [{"requirementIds": [requirement_id], "time": {"startMs": 0, "endMs": 500}}],
        "pickupOfShotId": None,
    }
    if invalid == "out_of_range_event":
        content["events"][0]["time"]["endMs"] = 1001
    elif invalid == "unbound_event":
        content["events"][0]["requirementIds"] = [str(uuid4())]
    else:
        content["pickupOfShotId"] = shot_id
    with connect(directory / "project.sqlite3", "ro") as db:
        with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
            storyboard.validate_formal(db, {"kind": "shot", "content": content})


def test_verification_false_keeps_reference_incompatible(project_fixture: tuple) -> None:
    service, directory, session = project_fixture
    media_id, digest = str(uuid4()), "a" * 64
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute(
            "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                media_id,
                "media/test.png",
                digest,
                1,
                "image/png",
                None,
                10,
                10,
                "available",
                "imported",
                "{}",
            ),
        )
    body = request(
        {
            "references": [
                {
                    "mediaId": media_id,
                    "mediaHash": digest,
                    "role": "firstFrame",
                    "state": "imported",
                }
            ]
        },
        "shot",
    )
    save(service, session, body)
    receipt = mutate(
        service,
        session,
        "verify_reference",
        {
            "draftId": body["payload"]["draftId"],
            "mediaId": media_id,
            "role": "firstFrame",
            "matchesPurpose": False,
            "note": "wrong beginning",
        },
    )
    assert receipt["state"] == "committed"
    args = (session["projectId"], session["projectSessionId"], 1)
    assert (
        service.get_draft(*args, body["payload"]["draftId"])["content"]["content"]["references"][0][
            "state"
        ]
        == "incompatible"
    )


def test_verified_reference_freezes_provenance_and_rejects_changed_purpose(
    project_fixture: tuple,
) -> None:
    service, directory, session = project_fixture
    args = (session["projectId"], session["projectSessionId"], 1)
    media_id, digest = str(uuid4()), "a" * 64
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute(
            "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                media_id,
                "media/test.png",
                digest,
                1,
                "image/png",
                None,
                10,
                10,
                "available",
                "imported",
                "{}",
            ),
        )
    reference = {
        "mediaId": media_id,
        "mediaHash": digest,
        "role": "identity",
        "order": 0,
        "state": "imported",
        "keep": [],
        "ignore": [],
        "crop": None,
    }
    body = request(
        {
            "assetType": "character",
            "name": "A",
            "identityAnchors": ["face"],
            "allowedChanges": [],
            "states": [],
            "references": [reference],
        },
        "asset",
    )
    save(service, session, body)
    mutate(
        service,
        session,
        "verify_reference",
        {
            "draftId": body["payload"]["draftId"],
            "mediaId": media_id,
            "role": "identity",
            "matchesPurpose": True,
            "note": "Correct identity",
        },
    )
    artifact = body["payload"]["artifactId"]
    revision = service.create_revision(
        *args,
        artifact,
        {
            "clientOperationId": str(uuid4()),
            "expectedRevision": service.get_project(*args)["revision"],
            "payload": {"draftId": body["payload"]["draftId"]},
        },
    )["resourceId"]
    with connect(directory / "project.sqlite3", "ro") as db:
        verified = service.get_draft(*args, body["payload"]["draftId"])["content"]["content"]
        assert storyboard.adopted_reference_usable(db, revision, verified["references"][0])
    body["clientOperationId"] = str(uuid4())
    body["expectedRevision"] = service.get_project(*args)["revision"]
    body["payload"]["content"]["content"]["name"] = "B"
    body["payload"]["content"]["content"]["references"][0]["state"] = "verified"
    save(service, session, body)
    edited = service.get_draft(*args, body["payload"]["draftId"])
    assert edited["content"]["content"]["references"][0]["state"] == "pending"


def test_v6_read_only_rejects_storyboard_then_write_backfills_shot(project_fixture: tuple) -> None:
    service, directory, session = project_fixture
    shot_id = str(uuid4())
    save(service, session, request({"shotId": shot_id}, "shot"))
    service.close()
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute("DROP TABLE revision_reference_verifications")
        db.execute("DROP INDEX verification_draft_idx")
        db.execute("DROP TABLE reference_verifications")
        db.execute("DROP TABLE storyboard_shots")
        db.execute("PRAGMA user_version=6")
    restarted = ProjectService(service.app_data_dir)
    try:
        old = restarted.open_project(
            {
                "directoryGrantId": grant(restarted, directory, "openProject", 1),
                "requestedMode": "read",
            },
            1,
        )
        with pytest.raises(ProjectError, match="PROJECT_VERSION_UNSUPPORTED"):
            restarted.get_storyboard(old["projectId"], old["projectSessionId"], 1)
        restarted.close_session(old["projectSessionId"], 1)
        from tests.storage.test_drafts import open_session

        writable = open_session(restarted, directory)
        assert restarted.get_storyboard(writable["projectId"], writable["projectSessionId"], 1)[
            "shotIds"
        ] == [shot_id]
    finally:
        restarted.close()
