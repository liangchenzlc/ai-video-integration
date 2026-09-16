import copy
import json
from pathlib import Path
from uuid import uuid4

from app.services.task_adapter import SyntheticAdapter
from app.storage import candidates
from app.storage.database import connect
from tests.storage.test_drafts import request, save
from tests.storage.test_task_plans import budget, cmd, invoke, plan
from tests.tasks.test_executor import start, wait_task


class ResultAdapter(SyntheticAdapter):
    def __init__(self, transform=None):
        self.transform = transform

    def submit(self, request, submission_token):
        response = super().submit(request, submission_token)
        if self.transform is not None:
            response["result"] = self.transform(response["result"])
        return response


def test_text_result_creates_persisted_revision_without_adoption(opened):
    service, directory, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])

    assert task["state"] == "complete"
    assert len(task["candidateRevisionIds"]) == 1
    page = invoke(service, session, "list_task_candidates", task["id"], None, 50)
    assert [item["id"] for item in page["items"]] == task["candidateRevisionIds"]
    assert page["items"][0]["artifactId"] == frozen["objectId"]
    with connect(directory / "project.sqlite3", "ro") as db:
        artifact = db.execute(
            "SELECT adopted_revision_id,confirmed_revision_id FROM artifacts WHERE id=?",
            (frozen["objectId"],),
        ).fetchone()
        assert tuple(artifact) == (None, None)
        result = db.execute("SELECT * FROM candidate_results").fetchone()
        assert result["result_ordinal"] == 0
        assert result["parse_state"] == "registered"
        assert result["revision_id"] == task["candidateRevisionIds"][0]


def test_invalid_structured_result_retains_raw_response_and_static_error(opened):
    service, directory, session = opened
    service._tasks.adapter = ResultAdapter(
        lambda result: {
            "resultProtocolVersion": "candidate-v1",
            "payload": {"kind": "story", "content": {"sourceText": "private raw sentinel"}},
        }
    )
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])

    assert task["state"] == "failed"
    assert task["candidateRevisionIds"] == []
    call = invoke(service, session, "get_call", task["callIds"][0])
    assert call["errorCode"] == "STRUCTURED_RESULT_INVALID"
    assert "private raw sentinel" not in json.dumps(call)
    with connect(directory / "project.sqlite3", "ro") as db:
        result = db.execute("SELECT * FROM candidate_results").fetchone()
        assert result["parse_state"] == "invalid"
        assert result["error_code"] == "STRUCTURED_RESULT_INVALID"
        assert "private raw sentinel" in result["raw_result_json"]
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0


def test_missing_candidate_protocol_is_invalid_for_new_protocol_call(opened):
    service, directory, session = opened
    service._tasks.adapter = ResultAdapter(
        lambda result: {"payload": result["payload"], "privateRaw": "retained"}
    )
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "failed"
    with connect(directory / "project.sqlite3", "ro") as db:
        row = db.execute("SELECT parse_state,raw_result_json FROM candidate_results").fetchone()
        assert row["parse_state"] == "invalid"
        assert "privateRaw" in row["raw_result_json"]


def test_legacy_schema_task_read_does_not_query_candidate_table(opened, monkeypatch):
    service, directory, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    monkeypatch.setattr(service._tasks.executor, "enqueue", lambda *args: None)
    receipt, _ = start(service, session, frozen)
    with connect(directory / "project.sqlite3") as db, db:
        db.execute("DROP TABLE candidate_results")
        db.execute("PRAGMA user_version=5")
    task = invoke(service, session, "get_task", receipt["resourceId"])
    assert task["candidateRevisionIds"] == []


def test_story_phase_cannot_change_frozen_or_out_of_stage_fields(opened):
    def alter(result):
        changed = copy.deepcopy(result)
        changed["payload"]["content"]["outline"] = ["not allowed during adaptation"]
        return changed

    service, directory, session = opened
    service._tasks.adapter = ResultAdapter(alter)
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "failed"
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT parse_state FROM candidate_results").fetchone()[0] == "invalid"


def test_registering_same_call_ordinal_replays_original_revision(opened, monkeypatch):
    service, directory, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    monkeypatch.setattr(service._tasks.executor, "enqueue", lambda *args: None)
    receipt, _ = start(service, session, frozen)
    task = invoke(service, session, "get_task", receipt["resourceId"])
    with connect(directory / "project.sqlite3") as db, db:
        call_id = task["callIds"][0]
        snapshot = json.loads(
            db.execute(
                "SELECT request_snapshot_json FROM service_calls WHERE id=?", (call_id,)
            ).fetchone()[0]
        )
        raw = SyntheticAdapter().submit(snapshot, "token")["result"]
        first = candidates.register_text_result(db, call_id, 0, raw)
        second = candidates.register_text_result(db, call_id, 0, raw)
        assert second == first
        assert db.execute("SELECT count(*) FROM candidate_results").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1


def test_image_download_recovery_publishes_one_pending_reference_without_resubmit(
    opened, monkeypatch
):
    service, directory, session = opened

    class ImageAdapter(SyntheticAdapter):
        submits = 0

        def submit(self, request, submission_token):
            self.submits += 1
            return super().submit(request, submission_token)

    adapter = ImageAdapter()
    service._tasks.adapter = adapter
    invoke(
        service,
        session,
        "set_budget",
        cmd(
            service,
            session,
            {
                "totalMicroCny": 10_000_000,
                "allocations": [{"stage": "image", "limitMicroCny": 10_000_000}],
                "warningPercent": 80,
            },
        ),
    )
    body = request(
        {
            "assetType": "character",
            "name": "Hero",
            "identityAnchors": ["round glasses"],
            "allowedChanges": [],
            "states": [],
            "references": [],
        },
        "asset",
        service.get_project(session["projectId"], session["projectSessionId"], 1)["revision"],
    )
    save(service, session, body)
    planned = invoke(
        service,
        session,
        "plan_task",
        cmd(
            service,
            session,
            {
                "objectId": body["payload"]["artifactId"],
                "stage": "image",
                "phase": "image_character",
                "goal": "candidate portrait",
                "inputRevisionIds": [],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            },
        ),
    )
    frozen = invoke(service, session, "get_task_plan", planned["resourceId"])
    receipt, _ = start(service, session, frozen)
    pending = wait_task(service, session, receipt["resourceId"])
    assert pending["state"] == "pending_download"
    assert adapter.submits == 1

    record = {
        "id": str(uuid4()),
        "relativePath": "media/generated.image",
        "sha256": "a" * 64,
        "byteLength": 128,
        "mime": "image/png",
        "durationMs": None,
        "width": 64,
        "height": 48,
        "provenance": "synthetic",
        "callId": pending["callIds"][0],
        "ordinal": 0,
        "sourceFingerprint": "b" * 64,
    }
    monkeypatch.setattr(
        "app.services.generated_media.publish_image", lambda *args, **kwargs: dict(record)
    )
    with connect(service._application) as app, app:
        app.execute("UPDATE settings SET ffmpeg_path=?", (str(Path("C:/tools/ffmpeg.exe")),))
    invoke(
        service,
        session,
        "recover_call",
        pending["callIds"][0],
        cmd(service, session, {"action": "download"}),
    )
    complete = wait_task(service, session, pending["id"])
    assert complete["state"] == "complete"
    assert adapter.submits == 1
    assert invoke(service, session, "get_call", pending["callIds"][0])["resultMediaIds"] == [
        record["id"]
    ]
    candidate = invoke(service, session, "list_task_candidates", pending["id"])["items"][0]
    reference = candidate["payload"]["content"]["references"][-1]
    assert reference == {
        "mediaId": record["id"],
        "mediaHash": "a" * 64,
        "role": "identity",
        "order": 0,
        "state": "pending",
        "keep": [],
        "ignore": [],
        "crop": None,
    }
    with connect(directory / "project.sqlite3", "ro") as db:
        row = db.execute("SELECT media_id,revision_id FROM candidate_results").fetchone()
        assert row["media_id"] == record["id"]
        assert row["revision_id"] == complete["candidateRevisionIds"][0]


def test_non_candidate_video_stage_keeps_legacy_result_flow(opened):
    service, directory, session = opened
    invoke(
        service,
        session,
        "set_budget",
        cmd(
            service,
            session,
            {
                "totalMicroCny": 10_000_000,
                "allocations": [{"stage": "video", "limitMicroCny": 10_000_000}],
                "warningPercent": 80,
            },
        ),
    )
    body = request(
        {"purpose": "A shot", "startState": "A", "endState": "B", "plannedMs": 3000},
        "shot",
        service.get_project(session["projectId"], session["projectSessionId"], 1)["revision"],
    )
    save(service, session, body)
    planned = invoke(
        service,
        session,
        "plan_task",
        cmd(
            service,
            session,
            {
                "objectId": body["payload"]["artifactId"],
                "stage": "video",
                "phase": "video",
                "goal": "legacy fixture video",
                "inputRevisionIds": [],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            },
        ),
    )
    frozen = invoke(service, session, "get_task_plan", planned["resourceId"])
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "complete"
    assert task["candidateRevisionIds"] == []
    with connect(directory / "project.sqlite3", "ro") as db:
        snapshot = json.loads(
            db.execute("SELECT request_snapshot_json FROM service_calls").fetchone()[0]
        )
        assert "resultProtocolVersion" not in snapshot
        assert db.execute("SELECT count(*) FROM candidate_results").fetchone()[0] == 0


def test_video_image_claim_never_reaches_publisher(opened, monkeypatch):
    service, _, session = opened

    class InvalidImageAdapter(SyntheticAdapter):
        def submit(self, request, submission_token):
            return {
                "remoteTaskId": "synthetic-" + submission_token,
                "result": {
                    "resultProtocolVersion": "candidate-v1",
                    "resultType": "image",
                    "synthetic": False,
                    "resultRef": "https://example.com/private.png",
                },
            }

    service._tasks.adapter = InvalidImageAdapter()
    publishes = []
    monkeypatch.setattr(
        "app.services.generated_media.publish_image",
        lambda *args, **kwargs: publishes.append((args, kwargs)),
    )
    invoke(
        service,
        session,
        "set_budget",
        cmd(
            service,
            session,
            {
                "totalMicroCny": 10_000_000,
                "allocations": [{"stage": "video", "limitMicroCny": 10_000_000}],
                "warningPercent": 80,
            },
        ),
    )
    body = request(
        {"purpose": "A shot", "startState": "A", "endState": "B", "plannedMs": 3000},
        "shot",
        service.get_project(session["projectId"], session["projectSessionId"], 1)["revision"],
    )
    save(service, session, body)
    planned = invoke(
        service,
        session,
        "plan_task",
        cmd(
            service,
            session,
            {
                "objectId": body["payload"]["artifactId"],
                "stage": "video",
                "phase": "video",
                "goal": "video result",
                "inputRevisionIds": [],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            },
        ),
    )
    frozen = invoke(service, session, "get_task_plan", planned["resourceId"])
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "failed"
    assert publishes == []
