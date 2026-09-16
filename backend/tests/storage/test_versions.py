import hashlib
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_drafts import opened as opened
from tests.storage.test_drafts import request, save

Json = dict[str, Any]


def command(revision: int, payload: Json) -> Json:
    return {"clientOperationId": str(uuid4()), "expectedRevision": revision, "payload": payload}


def context(
    opened: tuple[ProjectService, Path, Json],
) -> tuple[ProjectService, tuple[str, str, int]]:
    service, _, session = opened
    return service, (session["projectId"], session["projectSessionId"], 1)


def candidate(
    opened: tuple[ProjectService, Path, Json],
    text: str = "Original",
    artifact: str | None = None,
    kind: str = "story",
    content: Json | None = None,
    parent: str | None = None,
) -> tuple[str, str]:
    service, directory, session = opened
    with connect(directory / "project.sqlite3", "ro") as db:
        revision = db.execute("SELECT revision FROM projects").fetchone()[0]
    body = request(
        content or {"sourceText": text, "brief": "A brief", "inputType": "idea"}, kind, revision
    )
    if artifact:
        body["payload"]["artifactId"] = artifact
    body["payload"]["baseRevisionId"] = parent
    saved = save(service, session, body)
    receipt = service.create_revision(
        *context(opened)[1],
        body["payload"]["artifactId"],
        command(saved["committedRevision"], {"draftId": body["payload"]["draftId"]}),
    )
    return body["payload"]["artifactId"], receipt["resourceId"]


def current(opened: tuple[ProjectService, Path, Json]) -> int:
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        return int(db.execute("SELECT revision FROM projects").fetchone()[0])


def adopt(
    opened: tuple[ProjectService, Path, Json], artifact: str, revision: str, confirm: bool = False
) -> Json:
    service, args = context(opened)
    impact = service.preview_adoption(
        *args, artifact, {"toRevisionId": revision, "expectedRevision": current(opened)}
    )
    return service.adopt_revision(
        *args,
        artifact,
        command(
            current(opened),
            {"previewId": impact["previewId"], "toRevisionId": revision, "confirm": confirm},
        ),
    )


def test_immutable_candidate_preserves_exact_text_without_adoption(
    opened: tuple[ProjectService, Path, Json],
) -> None:
    service, args = context(opened)
    artifact, first = candidate(opened, "A\r\nB")
    _, second = candidate(opened, "A\r\nC", artifact, parent=first)
    page = service.list_revisions(*args, artifact, limit=1)
    next_page = service.list_revisions(*args, artifact, cursor=page["nextCursor"], limit=1)
    revisions = page["items"] + next_page["items"]
    assert {r["id"] for r in revisions} == {first, second}
    assert len({r["contentHash"] for r in revisions}) == 2
    assert (
        revisions[0]["payload"]["content"]["sourceHash"]
        == hashlib.sha256(revisions[0]["payload"]["content"]["sourceText"].encode()).hexdigest()
    )
    assert service.get_artifact(*args, artifact) == {
        "id": artifact,
        "kind": "story",
        "adoptedRevisionId": None,
        "confirmedRevisionId": None,
        "needsUpdate": False,
        "latestAdoptionId": None,
    }
    with connect(opened[1] / "project.sqlite3") as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE revisions SET content_hash=? WHERE id=?", ("a" * 64, first))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM revisions WHERE id=?", (first,))


def test_incomplete_candidate_rolls_back_artifact(
    opened: tuple[ProjectService, Path, Json],
) -> None:
    service, _, session = opened
    body = request({})
    save(service, session, body)
    with pytest.raises(ProjectError, match="INPUT_INCOMPLETE"):
        service.create_revision(
            *context(opened)[1],
            body["payload"]["artifactId"],
            command(2, {"draftId": body["payload"]["draftId"]}),
        )
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 0
    assert current(opened) == 2


def test_adoption_confirmation_undo_and_replay(opened: tuple[ProjectService, Path, Json]) -> None:
    service, args = context(opened)
    artifact, first = candidate(opened)
    adopted = adopt(opened, artifact, first)
    with pytest.raises(ProjectError, match="CHECK_REQUIRED"):
        service.confirm_revision(
            *args, artifact, command(current(opened), {"revisionId": first, "checkIds": []})
        )
    checked = service.run_local_checks(
        *args,
        command(current(opened), {"revisionIds": [first], "ruleIds": ["structural", "references"]}),
    )
    assert checked["state"] == "accepted"
    job = service.get_job(*args, checked["resourceId"])
    report = service.get_check_report(*args, job["resultId"])
    assert report["outcome"] == "pass" and report["method"] == "local"
    assert report["ruleIds"] == ["structural", "references"]
    service.confirm_revision(
        *args, artifact, command(current(opened), {"revisionId": first, "checkIds": [report["id"]]})
    )
    _, second = candidate(opened, "Modified", artifact, parent=first)
    second_adoption = adopt(opened, artifact, second)
    assert service.get_artifact(*args, artifact)["confirmedRevisionId"] == first
    undo_command = command(current(opened), {"adoptionId": second_adoption["resourceId"]})
    undone = service.undo_adoption(*args, second_adoption["resourceId"], undo_command)
    assert service.undo_adoption(*args, second_adoption["resourceId"], undo_command) == undone
    assert service.get_artifact(*args, artifact)["adoptedRevisionId"] == first
    assert service.get_artifact(*args, artifact)["confirmedRevisionId"] == first
    assert len(service.list_revisions(*args, artifact)["items"]) == 2
    with pytest.raises(ProjectError, match="UNDO_CONFLICT"):
        service.undo_adoption(
            *args,
            adopted["resourceId"],
            command(current(opened), {"adoptionId": adopted["resourceId"]}),
        )


def test_preview_replay_binds_route_and_stales(opened: tuple[ProjectService, Path, Json]) -> None:
    service, args = context(opened)
    artifact, first = candidate(opened)
    impact = service.preview_adoption(
        *args, artifact, {"toRevisionId": first, "expectedRevision": current(opened)}
    )
    body = command(
        current(opened), {"previewId": impact["previewId"], "toRevisionId": first, "confirm": False}
    )
    receipt = service.adopt_revision(*args, artifact, body)
    service._versions.previews.clear()
    assert service.adopt_revision(*args, artifact, body) == receipt
    with pytest.raises(ProjectError, match="OPERATION_ID_REUSED"):
        service.adopt_revision(*args, str(uuid4()), body)
    with pytest.raises(ProjectError, match="PREVIEW_STALE"):
        service.adopt_revision(*args, artifact, command(current(opened), body["payload"]))


def test_formal_task_snapshot_locks_inputs_but_allows_drafts_and_unrelated_adoption(
    opened, monkeypatch
):
    from tests.storage.test_task_plans import budget

    service, args = context(opened)
    budget(service, opened[2])
    artifact, first = candidate(opened)
    adopt(opened, artifact, first)
    receipt = service.plan_task(
        *args,
        command(
            current(opened),
            {
                "objectId": artifact,
                "stage": "story",
                "phase": "story_adaptation",
                "goal": "Adapt",
                "inputRevisionIds": [first],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            },
        ),
    )
    plan = service.get_task_plan(*args, receipt["resourceId"])
    monkeypatch.setattr(service._tasks.executor, "enqueue", lambda *args: None)
    started = service.start_task(
        *args,
        command(
            current(opened),
            {
                "planId": plan["id"],
                "authorizedMaximumMicroCny": plan["maximumMicroCny"],
                "disclosureAccepted": True,
            },
        ),
    )
    _, second = candidate(opened, "Modified", artifact)
    with pytest.raises(ProjectError, match="INPUT_LOCKED"):
        adopt(opened, artifact, second)
    other, other_revision = candidate(opened, "Unrelated")
    adopt(opened, other, other_revision)
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        assert (
            db.execute(
                "SELECT revision_id FROM task_inputs WHERE task_id=?", (started["resourceId"],)
            ).fetchone()[0]
            == first
        )
        import json

        snapshot = json.loads(
            db.execute("SELECT request_snapshot_json FROM service_calls").fetchone()[0]
        )
        assert snapshot["inputRevisions"][0]["id"] == first
        assert snapshot["inputRevisions"][0]["payload"]["content"]["sourceText"] == "Original"


def test_real_accounting_and_retained_results_are_invariant_across_adopt_undo(opened):
    from tests.storage.test_task_plans import budget, plan
    from tests.tasks.test_executor import start, wait_task

    service, args = context(opened)
    budget(service, opened[2])
    frozen, _ = plan(service, opened[2])
    started, _ = start(service, opened[2], frozen)
    assert wait_task(service, opened[2], started["resourceId"])["state"] == "complete"
    artifact, first = candidate(opened)
    adopt(opened, artifact, first)
    _, second = candidate(opened, "Second", artifact)

    def costs_and_calls():
        with connect(opened[1] / "project.sqlite3", "ro") as db:
            return {
                table: [tuple(row) for row in db.execute("SELECT * FROM " + table)]
                for table in (
                    "cost_entries",
                    "service_calls",
                    "call_events",
                    "media_files",
                    "external_expenses",
                )
            }

    baseline = costs_and_calls()
    assert baseline["cost_entries"] and baseline["service_calls"]
    adopted = adopt(opened, artifact, second)
    candidate(opened, "Retained third", artifact)
    service.undo_adoption(
        *args,
        adopted["resourceId"],
        command(current(opened), {"adoptionId": adopted["resourceId"]}),
    )
    assert costs_and_calls() == baseline
    assert len(service.list_revisions(*args, artifact)["items"]) == 3


def test_cross_artifact_parent_and_failed_adoption_transaction(opened, monkeypatch):
    from app.storage import adoptions

    service, args = context(opened)
    a, first = candidate(opened)
    b, second = candidate(opened)
    with pytest.raises(ProjectError):
        candidate(opened, "Wrong parent", b, parent=first)
    with connect(opened[1] / "project.sqlite3") as db:
        db.execute("BEGIN")
        db.execute("UPDATE artifacts SET adopted_revision_id=? WHERE id=?", (first, b))
        with pytest.raises(sqlite3.IntegrityError):
            db.commit()
        db.rollback()
    initial = service.get_artifact(*args, a)
    original = adoptions.snapshot

    def fail_after_update(db, ids):
        value = original(db, ids)
        if value["artifacts"][0]["adoptedRevisionId"]:
            raise sqlite3.OperationalError("injected after pointer change")
        return value

    monkeypatch.setattr(adoptions, "snapshot", fail_after_update)
    with pytest.raises(ProjectError, match="STORAGE_UNAVAILABLE"):
        adopt(opened, a, first)
    assert service.get_artifact(*args, a) == initial
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM adoptions").fetchone()[0] == 0


def asset_payload(color="blue"):
    return {
        "assetType": "character",
        "name": "Character",
        "identityAnchors": [color],
        "allowedChanges": [],
        "states": [],
        "references": [],
    }


def shot_payload(asset_revision, scene_id):
    return {
        "shotId": str(uuid4()),
        "purpose": "A shot",
        "sceneId": scene_id,
        "assetRevisionIds": [asset_revision],
        "requirementIds": [],
        "startState": "Start",
        "events": [],
        "endState": "End",
        "camera": "Still",
        "subjectHand": "none",
        "plannedMs": 5000,
        "dialogueIds": [],
        "references": [],
        "videoMediaId": None,
        "pickupOfShotId": None,
        "use": "original",
    }


def test_visual_adoption_marks_only_real_downstream_and_undo_restores_flags(opened):
    service, args = context(opened)
    scene = str(uuid4())
    story, story_revision = candidate(
        opened,
        content={
            "sourceText": "Scene",
            "inputType": "idea",
            "brief": "Brief",
            "scenes": [
                {
                    "id": scene,
                    "title": "Scene",
                    "action": "Move",
                    "plannedMs": 5000,
                    "locationAssetId": None,
                }
            ],
        },
    )
    adopt(opened, story, story_revision)
    actor, first = candidate(opened, kind="asset", content=asset_payload())
    adopt(opened, actor, first)
    shot, shot_revision = candidate(opened, kind="shot", content=shot_payload(first, scene))
    adopt(opened, shot, shot_revision)
    unrelated, unrelated_revision = candidate(opened)
    adopt(opened, unrelated, unrelated_revision)
    _, second = candidate(opened, artifact=actor, kind="asset", content=asset_payload("red"))
    assert not service.get_artifact(*args, shot)["needsUpdate"]
    impact = service.preview_adoption(
        *args, actor, {"toRevisionId": second, "expectedRevision": current(opened)}
    )
    assert impact["affectedArtifactIds"] == [shot]
    assert "dialogueAudio" not in impact["affectedScopes"]
    receipt = adopt(opened, actor, second)
    assert service.get_artifact(*args, shot)["needsUpdate"]
    assert not service.get_artifact(*args, unrelated)["needsUpdate"]
    service.undo_adoption(
        *args,
        receipt["resourceId"],
        command(current(opened), {"adoptionId": receipt["resourceId"]}),
    )
    assert not service.get_artifact(*args, shot)["needsUpdate"]


def test_missing_scene_reference_rejected_without_candidate(opened):
    actor, first = candidate(opened, kind="asset", content=asset_payload())
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        candidate(opened, kind="shot", content=shot_payload(first, str(uuid4())))


def test_confirmation_cannot_reuse_old_report_or_empty_rules(opened):
    service, args = context(opened)
    artifact, first = candidate(opened)
    checked = service.run_local_checks(
        *args,
        command(current(opened), {"revisionIds": [first], "ruleIds": ["structural", "references"]}),
    )
    check_id = service.get_job(*args, checked["resourceId"])["resultId"]
    _, second = candidate(opened, "New", artifact)
    adopt(opened, artifact, second)
    with pytest.raises(ProjectError, match="CHECK_REQUIRED"):
        service.confirm_revision(
            *args,
            artifact,
            command(current(opened), {"revisionId": second, "checkIds": [check_id]}),
        )
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        service.run_local_checks(
            *args, command(current(opened), {"revisionIds": [second], "ruleIds": []})
        )


def test_undo_rejects_confirmation_edit_after_adoption(opened):
    service, args = context(opened)
    artifact, first = candidate(opened)
    receipt = adopt(opened, artifact, first)
    checked = service.run_local_checks(
        *args,
        command(current(opened), {"revisionIds": [first], "ruleIds": ["structural", "references"]}),
    )
    check_id = service.get_job(*args, checked["resourceId"])["resultId"]
    service.confirm_revision(
        *args, artifact, command(current(opened), {"revisionId": first, "checkIds": [check_id]})
    )
    with pytest.raises(ProjectError, match="UNDO_CONFLICT"):
        service.undo_adoption(
            *args,
            receipt["resourceId"],
            command(current(opened), {"adoptionId": receipt["resourceId"]}),
        )


def media_fixture(opened, mime="image/png"):
    import hashlib

    media_id = str(uuid4())
    content = b"retained original media bytes"
    digest = hashlib.sha256(content).hexdigest()
    path = opened[1] / "media" / (media_id + ".bin")
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(content)
    with connect(opened[1] / "project.sqlite3") as db, db:
        db.execute(
            "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                media_id,
                "media/" + path.name,
                digest,
                len(content),
                mime,
                1000,
                None,
                None,
                "available",
                "imported",
                "{}",
            ),
        )
    return media_id, digest, path


def test_task_freezes_transitive_dependencies_and_their_media(opened):
    from tests.storage.test_task_plans import budget

    service, args = context(opened)
    budget(service, opened[2])
    scene = str(uuid4())
    story, story_revision = candidate(
        opened,
        content={
            "sourceText": "Scene",
            "inputType": "idea",
            "brief": "Brief",
            "scenes": [
                {
                    "id": scene,
                    "title": "Scene",
                    "action": "Move",
                    "plannedMs": 5000,
                    "locationAssetId": None,
                }
            ],
        },
    )
    adopt(opened, story, story_revision)
    media_id, digest, _ = media_fixture(opened)
    content = asset_payload()
    content["references"] = [
        {
            "mediaId": media_id,
            "mediaHash": digest,
            "role": "identity",
            "order": 0,
            "state": "verified",
            "keep": [],
            "ignore": [],
            "crop": None,
        }
    ]
    actor, actor_revision = candidate(opened, kind="asset", content=content)
    adopt(opened, actor, actor_revision)
    shot, shot_revision = candidate(
        opened, kind="shot", content=shot_payload(actor_revision, scene)
    )
    adopt(opened, shot, shot_revision)
    receipt = service.plan_task(
        *args,
        command(
            current(opened),
            {
                "objectId": shot,
                "stage": "video",
                "phase": "video",
                "goal": "Animate",
                "inputRevisionIds": [shot_revision],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            },
        ),
    )
    plan = service.get_task_plan(*args, receipt["resourceId"])
    assert set(plan["inputRevisionIds"]) == {shot_revision, actor_revision, story_revision}
    assert plan["inputMediaHashes"] == [digest]


def test_local_reference_failure_has_persistent_issue_and_cannot_confirm(opened):
    service, args = context(opened)
    media_id, digest, path = media_fixture(opened)
    actor_payload = asset_payload()
    actor_payload["references"] = [
        {
            "mediaId": media_id,
            "mediaHash": digest,
            "role": "identity",
            "order": 0,
            "state": "verified",
            "keep": [],
            "ignore": [],
            "crop": None,
        }
    ]
    actor, revision = candidate(opened, kind="asset", content=actor_payload)
    adopt(opened, actor, revision)
    with connect(opened[1] / "project.sqlite3") as db, db:
        db.execute("UPDATE media_files SET availability='missing' WHERE id=?", (media_id,))
    receipt = service.run_local_checks(
        *args,
        command(
            current(opened), {"revisionIds": [revision], "ruleIds": ["structural", "references"]}
        ),
    )
    check_id = service.get_job(*args, receipt["resourceId"])["resultId"]
    report = service.get_check_report(*args, check_id)
    assert report["outcome"] == "fail" and len(report["issueIds"]) == 1
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        issue = db.execute(
            "SELECT rule_id,status FROM checks WHERE id=?", (report["issueIds"][0],)
        ).fetchone()
        assert tuple(issue) == ("references", "open")
    with pytest.raises(ProjectError, match="CHECK_REQUIRED"):
        service.confirm_revision(
            *args, actor, command(current(opened), {"revisionId": revision, "checkIds": [check_id]})
        )
    assert path.read_bytes() == b"retained original media bytes"


def test_draft_task_also_freezes_real_references_when_input_ids_omitted(opened, monkeypatch):
    from tests.storage.test_task_plans import budget

    service, args = context(opened)
    budget(service, opened[2])
    scene = str(uuid4())
    story, story_revision = candidate(
        opened,
        content={
            "sourceText": "Scene",
            "inputType": "idea",
            "brief": "Brief",
            "scenes": [
                {
                    "id": scene,
                    "title": "Scene",
                    "action": "Move",
                    "plannedMs": 5000,
                    "locationAssetId": None,
                }
            ],
        },
    )
    adopt(opened, story, story_revision)
    actor, first = candidate(opened, kind="asset", content=asset_payload())
    adopt(opened, actor, first)
    body = request(shot_payload(first, scene), "shot", current(opened))
    save(service, opened[2], body)
    receipt = service.plan_task(
        *args,
        command(
            current(opened),
            {
                "objectId": body["payload"]["artifactId"],
                "stage": "video",
                "phase": "video",
                "goal": "Animate",
                "inputRevisionIds": [],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            },
        ),
    )
    plan = service.get_task_plan(*args, receipt["resourceId"])
    assert set(plan["inputRevisionIds"]) == {first, story_revision}
    from app.storage import task_plans

    with connect(opened[1] / "project.sqlite3", "ro") as db:
        task_plans.validate_current(db, plan, service._tasks.adapter)


def test_reopen_exposes_nearest_adoption_for_undo(opened):
    from tests.storage.test_drafts import open_session

    service, args = context(opened)
    artifact, first = candidate(opened)
    receipt = adopt(opened, artifact, first)
    service.close_session(args[1], 1)
    session = open_session(service, opened[1])
    args = (session["projectId"], session["projectSessionId"], 1)
    obj = service.get_artifact(*args, artifact)
    assert obj["latestAdoptionId"] == receipt["resourceId"]
    service.undo_adoption(
        *args,
        obj["latestAdoptionId"],
        command(current(opened), {"adoptionId": obj["latestAdoptionId"]}),
    )
    assert service.get_artifact(*args, artifact)["latestAdoptionId"] is None


def timeline_payload(source=None):
    track = str(uuid4())
    clips = (
        []
        if source is None
        else [
            {
                "id": str(uuid4()),
                "trackId": track,
                "shotId": None,
                "mediaId": None,
                "contentRevisionId": source,
                "startMs": 0,
                "inMs": 0,
                "outMs": 1000,
                "durationMs": 1000,
                "gainDb": 0,
                "linkedClipIds": [],
                "keyframes": [],
            }
        ]
    )
    return {
        "width": 1280,
        "height": 720,
        "fps": {"numerator": 24, "denominator": 1},
        "durationMs": 1000,
        "tracks": [{"id": track, "kind": "video", "order": 0, "muted": False}],
        "clips": clips,
        "transitions": [],
        "burnSubtitles": False,
    }


def test_object_dependency_cycle_rejected_at_preview(opened):
    service, args = context(opened)
    a, a1 = candidate(opened, kind="timeline", content=timeline_payload())
    adopt(opened, a, a1)
    b, b1 = candidate(opened, kind="timeline", content=timeline_payload(a1))
    adopt(opened, b, b1)
    _, a2 = candidate(opened, artifact=a, kind="timeline", content=timeline_payload(b1))
    with pytest.raises(ProjectError, match="DEPENDENCY_CYCLE"):
        service.preview_adoption(
            *args, a, {"toRevisionId": a2, "expectedRevision": current(opened)}
        )
    assert service.get_artifact(*args, a)["adoptedRevisionId"] == a1


def test_missing_location_and_internal_timeline_reference_rejected(opened):
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        candidate(
            opened,
            content={
                "sourceText": "Scene",
                "inputType": "idea",
                "brief": "Brief",
                "scenes": [
                    {
                        "id": str(uuid4()),
                        "title": "Scene",
                        "action": "Move",
                        "plannedMs": 5000,
                        "locationAssetId": str(uuid4()),
                    }
                ],
            },
        )
    _, revision = candidate(opened)
    timeline = timeline_payload(revision)
    timeline["clips"][0]["linkedClipIds"] = [str(uuid4())]
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        candidate(opened, kind="timeline", content=timeline)


def test_large_revision_pages_respect_byte_budget_and_oversize_keeps_draft(opened):
    from app.storage.settings import canonical

    service, args = context(opened)
    content = {
        "sourceText": "s" * 100000,
        "inputType": "idea",
        "brief": "Brief",
        "outline": ["o" * 4000] * 100,
        "adaptationNotes": ["n" * 2000] * 50,
    }
    artifact, first = candidate(opened, content=content)
    _, second = candidate(opened, artifact=artifact, content=content)
    page = service.list_revisions(*args, artifact)
    assert len(page["items"]) == 1 and page["nextCursor"]
    next_page = service.list_revisions(*args, artifact, cursor=page["nextCursor"])
    assert {page["items"][0]["id"], next_page["items"][0]["id"]} == {first, second}
    assert next_page["nextCursor"] is None
    assert len(canonical(page).encode()) < 800 * 1024
    content["adaptationNotes"] = ["n" * 4000] * 100
    body = request(content, revision=current(opened))
    saved = save(service, opened[2], body)
    with pytest.raises(ProjectError, match="REVISION_SIZE_LIMIT"):
        service.create_revision(
            *args,
            body["payload"]["artifactId"],
            command(saved["committedRevision"], {"draftId": body["payload"]["draftId"]}),
        )
    assert (
        service.get_draft(*args, body["payload"]["draftId"])["content"]["content"][
            "adaptationNotes"
        ]
        == content["adaptationNotes"]
    )
    assert current(opened) == saved["committedRevision"]


@pytest.mark.parametrize("outcome", ["fail", "unknown", "not_applicable"])
def test_empty_issue_report_without_pass_never_confirms(opened, outcome):
    import json

    service, args = context(opened)
    artifact, revision = candidate(opened)
    adopt(opened, artifact, revision)
    receipt = service.run_local_checks(
        *args,
        command(
            current(opened), {"revisionIds": [revision], "ruleIds": ["structural", "references"]}
        ),
    )
    check_id = service.get_job(*args, receipt["resourceId"])["resultId"]
    report = service.get_check_report(*args, check_id)
    assert report["issueIds"] == []
    report["outcome"] = outcome
    with connect(opened[1] / "project.sqlite3") as db, db:
        db.execute(
            "UPDATE check_runs SET outcome=?,report_json=? WHERE id=?",
            (outcome, json.dumps(report), check_id),
        )
    with pytest.raises(ProjectError, match="CHECK_REQUIRED"):
        service.confirm_revision(
            *args,
            artifact,
            command(current(opened), {"revisionId": revision, "checkIds": [check_id]}),
        )


def test_ambiguous_story_source_change_keeps_scene_review_obligation(opened):
    service, args = context(opened)
    scene = str(uuid4())
    content = {
        "sourceText": "Original",
        "inputType": "idea",
        "brief": "Brief",
        "scenes": [
            {
                "id": scene,
                "title": "Scene",
                "action": "Move",
                "plannedMs": 5000,
                "locationAssetId": None,
            }
        ],
    }
    story, first = candidate(opened, content=content)
    adopt(opened, story, first)
    actor, actor_revision = candidate(opened, kind="asset", content=asset_payload())
    adopt(opened, actor, actor_revision)
    shot, shot_revision = candidate(
        opened, kind="shot", content=shot_payload(actor_revision, scene)
    )
    adopt(opened, shot, shot_revision)
    content["sourceText"] = "Modified"
    _, second = candidate(opened, artifact=story, content=content)
    impact = service.preview_adoption(
        *args, story, {"toRevisionId": second, "expectedRevision": current(opened)}
    )
    assert shot in impact["affectedArtifactIds"]


def test_subtitle_punctuation_and_character_color_do_not_invalidate_audio(opened):
    service, args = context(opened)
    actor, actor_revision = candidate(opened, kind="asset", content=asset_payload())
    adopt(opened, actor, actor_revision)
    scene, dialogue = str(uuid4()), str(uuid4())
    story, story_revision = candidate(
        opened,
        content={
            "sourceText": "Hello",
            "inputType": "script",
            "brief": "Brief",
            "scenes": [
                {
                    "id": scene,
                    "title": "Scene",
                    "action": "Speak",
                    "plannedMs": 1000,
                    "locationAssetId": None,
                }
            ],
            "dialogues": [
                {
                    "id": dialogue,
                    "speakerAssetId": actor,
                    "text": "Hello",
                    "delivery": "VO",
                    "requirementIds": [],
                    "sceneId": scene,
                }
            ],
        },
    )
    adopt(opened, story, story_revision)
    media_id, _, path = media_fixture(opened, "audio/wav")
    speech, speech_revision = candidate(
        opened,
        kind="speech",
        content={
            "dialogueId": dialogue,
            "text": "Hello",
            "speakerAssetId": actor,
            "mediaId": media_id,
            "measuredMs": 1000,
            "voicedRanges": [],
            "timingMethod": "manual",
            "voicePreset": "voice",
            "pronunciationNotes": "",
        },
    )
    adopt(opened, speech, speech_revision)
    payload = {
        "audioRevisionId": speech_revision,
        "timingMethod": "manual",
        "cues": [
            {
                "id": str(uuid4()),
                "dialogueId": None,
                "text": "Hello",
                "time": {"startMs": 0, "endMs": 1000},
                "differsFromDialogue": False,
            }
        ],
    }
    subtitle, first = candidate(opened, kind="subtitle", content=payload)
    adopt(opened, subtitle, first)
    payload["cues"][0]["text"] = "Hello!"
    _, second = candidate(opened, artifact=subtitle, kind="subtitle", content=payload)
    impact = service.preview_adoption(
        *args, subtitle, {"toRevisionId": second, "expectedRevision": current(opened)}
    )
    assert "dialogueAudio" not in impact["affectedScopes"]
    assert speech not in impact["affectedArtifactIds"]
    adopt(opened, subtitle, second)
    _, changed_actor = candidate(opened, artifact=actor, kind="asset", content=asset_payload("red"))
    adopt(opened, actor, changed_actor)
    assert service.get_artifact(*args, speech)["adoptedRevisionId"] == speech_revision
    assert not service.get_artifact(*args, speech)["needsUpdate"]
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0
    assert path.read_bytes() == b"retained original media bytes"


def test_preview_ttl_and_session_identity_are_enforced(opened, monkeypatch):
    import time

    from tests.storage.test_drafts import open_session

    service, args = context(opened)
    artifact, revision = candidate(opened)
    impact = service.preview_adoption(
        *args, artifact, {"toRevisionId": revision, "expectedRevision": current(opened)}
    )
    body = command(
        current(opened),
        {"previewId": impact["previewId"], "toRevisionId": revision, "confirm": False},
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            "app.services.versions.time.monotonic", lambda: time.monotonic_ns() / 1e9 + 301
        )
        with pytest.raises(ProjectError, match="PREVIEW_STALE"):
            service.adopt_revision(*args, artifact, body)
    service.close_session(args[1], 1)
    session = open_session(service, opened[1])
    with pytest.raises(ProjectError, match="PREVIEW_STALE"):
        service.adopt_revision(session["projectId"], session["projectSessionId"], 1, artifact, body)


@pytest.mark.parametrize("probe", ["report", "plan"])
def test_unrelated_scene_edit_preserves_speech_semantic_input_and_exact_snapshot(opened, probe):
    import copy
    import json

    service, args = context(opened)
    actor, actor_revision = candidate(opened, kind="asset", content=asset_payload())
    adopt(opened, actor, actor_revision)
    scene, dialogue = str(uuid4()), str(uuid4())
    content = {
        "sourceText": "Hello",
        "inputType": "script",
        "brief": "Brief",
        "scenes": [
            {
                "id": scene,
                "title": "Scene",
                "action": "Original action",
                "plannedMs": 1000,
                "locationAssetId": None,
            }
        ],
        "dialogues": [
            {
                "id": dialogue,
                "speakerAssetId": actor,
                "text": "Hello",
                "delivery": "VO",
                "requirementIds": [],
                "sceneId": scene,
            }
        ],
    }
    story, story_revision = candidate(opened, content=content)
    adopt(opened, story, story_revision)
    media_id, _, _ = media_fixture(opened, "audio/wav")
    speech, speech_revision = candidate(
        opened,
        kind="speech",
        content={
            "dialogueId": dialogue,
            "text": "Hello",
            "speakerAssetId": actor,
            "mediaId": media_id,
            "measuredMs": 1000,
            "voicedRanges": [],
            "timingMethod": "manual",
            "voicePreset": "voice",
            "pronunciationNotes": "",
        },
    )

    def check():
        receipt = service.run_local_checks(
            *args,
            command(
                current(opened),
                {"revisionIds": [speech_revision], "ruleIds": ["structural", "references"]},
            ),
        )
        return service.get_check_report(
            *args, service.get_job(*args, receipt["resourceId"])["resultId"]
        )

    checked = check()
    adopt(opened, speech, speech_revision, confirm=True)
    assert checked["outcome"] == "pass"
    subtitle = None
    if probe == "plan":
        subtitle, subtitle_revision = candidate(
            opened,
            kind="subtitle",
            content={"audioRevisionId": speech_revision, "timingMethod": "manual", "cues": []},
        )
        adopt(opened, subtitle, subtitle_revision)
    content["scenes"][0]["action"] = "Only scene action changed"
    _, second_story = candidate(opened, artifact=story, content=copy.deepcopy(content))
    impact = service.preview_adoption(
        *args, story, {"toRevisionId": second_story, "expectedRevision": current(opened)}
    )
    assert speech not in impact["affectedArtifactIds"]
    adopt(opened, story, second_story)
    obj = service.get_artifact(*args, speech)
    assert obj["adoptedRevisionId"] == obj["confirmedRevisionId"] == speech_revision
    assert not obj["needsUpdate"]
    payload = {
        "objectId": speech,
        "stage": "speech",
        "phase": "speech",
        "goal": "Read",
        "inputRevisionIds": [speech_revision],
        "candidates": 1,
        "includePrecheck": False,
        "executionMode": "synthetic",
    }
    if probe == "report":
        assert check()["outcome"] == "pass"
    else:
        receipt = service.plan_task(*args, command(current(opened), payload))
        plan = service.get_task_plan(*args, receipt["resourceId"])
        assert (
            story_revision in plan["inputRevisionIds"]
            and second_story not in plan["inputRevisionIds"]
        )
        with connect(opened[1] / "project.sqlite3", "ro") as db:
            snapshot = json.loads(
                db.execute(
                    "SELECT snapshot_json FROM task_plan_inputs WHERE plan_id=? AND revision_id=?",
                    (plan["id"], story_revision),
                ).fetchone()[0]
            )
            assert snapshot["payload"]["content"]["scenes"][0]["action"] == "Original action"
        # Semantic equivalence applies to dependency edges, never to an explicit old root.
        old_root = dict(
            payload,
            objectId=story,
            stage="story",
            phase="story_adaptation",
            inputRevisionIds=[story_revision],
        )
        with pytest.raises(ProjectError, match="PLAN_STALE"):
            service.plan_task(*args, command(current(opened), old_root))
        from app.storage import task_plans

        # The generic snapshot walker also checks the scope at each level of a chain.
        # This exercises storage closure, not a nonexistent public subtitle task phase.
        with connect(opened[1] / "project.sqlite3", "ro") as db:
            closure = task_plans.input_snapshot(db, subtitle, [subtitle_revision])
            assert {item["id"] for item in closure["revisions"]} == {
                subtitle_revision,
                speech_revision,
                story_revision,
            }
    # A subsequent actual dialogue change must keep the opposite behavior.
    content["dialogues"][0]["text"] = "Changed dialogue"
    _, third_story = candidate(opened, artifact=story, content=content)
    impact = service.preview_adoption(
        *args, story, {"toRevisionId": third_story, "expectedRevision": current(opened)}
    )
    assert speech in impact["affectedArtifactIds"]
    adopt(opened, story, third_story)
    assert service.get_artifact(*args, speech)["needsUpdate"]
    assert check()["outcome"] == "fail"
    with pytest.raises(ProjectError, match="PLAN_STALE"):
        service.plan_task(*args, command(current(opened), payload))
    if subtitle is not None:
        assert service.get_artifact(*args, subtitle)["needsUpdate"]
        with connect(opened[1] / "project.sqlite3", "ro") as db:
            with pytest.raises(ProjectError, match="PLAN_STALE"):
                task_plans.input_snapshot(db, subtitle, [subtitle_revision])
    # Comparing only the newest pair would incorrectly forgive the older dialogue change.
    content["scenes"][0]["action"] = "Another unrelated scene edit"
    _, fourth_story = candidate(opened, artifact=story, content=content)
    adopt(opened, story, fourth_story)
    assert service.get_artifact(*args, speech)["needsUpdate"]
    assert check()["outcome"] == "fail"
    with pytest.raises(ProjectError, match="PLAN_STALE"):
        service.plan_task(*args, command(current(opened), payload))
