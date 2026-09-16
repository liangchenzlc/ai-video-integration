from uuid import uuid4

import pytest
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_drafts import opened as opened
from tests.storage.test_drafts import request, save


def cmd(service, session, payload):
    return {
        "clientOperationId": str(uuid4()),
        "expectedRevision": service.get_project(
            session["projectId"], session["projectSessionId"], 1
        )["revision"],
        "payload": payload,
    }


def invoke(service, session, method, *args):
    return getattr(service, method)(session["projectId"], session["projectSessionId"], 1, *args)


def budget(service, session, amount=10_000_000):
    return invoke(
        service,
        session,
        "set_budget",
        cmd(
            service,
            session,
            {
                "totalMicroCny": amount,
                "allocations": [{"stage": "story", "limitMicroCny": amount}],
                "warningPercent": 80,
            },
        ),
    )


def plan(service, session, candidates=1, mode="synthetic", content=None):
    body = request(
        content if content is not None else {"sourceText": "鍘熸枃", "brief": "鏀圭紪"},
        revision=service.get_project(session["projectId"], session["projectSessionId"], 1)[
            "revision"
        ],
    )
    save(service, session, body)
    command = cmd(
        service,
        session,
        {
            "objectId": body["payload"]["artifactId"],
            "stage": "story",
            "phase": "story_adaptation",
            "goal": "鐢熸垚鏁呬簨",
            "inputRevisionIds": [],
            "candidates": candidates,
            "includePrecheck": False,
            "executionMode": mode,
        },
    )
    receipt = invoke(service, session, "plan_task", command)
    return invoke(service, session, "get_task_plan", receipt["resourceId"]), command


def test_budget_and_plan_snapshot_replay(opened):
    service, directory, session = opened
    budget(service, session)
    frozen, command = plan(service, session)
    assert frozen["maximumMicroCny"] > 0
    assert frozen["inputPreview"]["payload"]["sourceText"] == "鍘熸枃"
    assert frozen["models"][0]["providerId"] == "synthetic-local"
    assert invoke(service, session, "plan_task", command)["resourceId"] == frozen["id"]
    assert invoke(service, session, "get_budget")["executionMode"] == "synthetic"
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0


@pytest.mark.parametrize("content", [{}, {"sourceText": "", "brief": "ok"}, {"sourceText": "ok"}])
def test_blank_drafts_save_but_cannot_plan(opened, content):
    service, _, session = opened
    budget(service, session)
    with pytest.raises(ProjectError, match="INPUT_INCOMPLETE"):
        plan(service, session, content=content)


def test_real_without_approved_price_rejected(opened):
    service, _, session = opened
    budget(service, session)
    with pytest.raises(ProjectError, match="CAPABILITY_MISSING"):
        plan(service, session, mode="real")


def test_budget_allocations_and_scope(opened):
    service, _, session = opened
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        invoke(
            service,
            session,
            "set_budget",
            cmd(
                service,
                session,
                {
                    "totalMicroCny": 10,
                    "allocations": [{"stage": "story", "limitMicroCny": 11}],
                    "warningPercent": 80,
                },
            ),
        )
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        service.get_budget(str(uuid4()), session["projectSessionId"], 1)


@pytest.mark.parametrize("target_ms", [3000, 4000])
def test_video_target_uses_five_second_request_and_price(opened, target_ms):
    service, _, session = opened
    body = request(
        {"purpose": "A shot", "startState": "A", "endState": "B", "plannedMs": target_ms}, "shot"
    )
    save(service, session, body)
    command = cmd(
        service,
        session,
        {
            "objectId": body["payload"]["artifactId"],
            "stage": "video",
            "phase": "video",
            "goal": "make video",
            "inputRevisionIds": [],
            "candidates": 1,
            "includePrecheck": False,
            "executionMode": "synthetic",
        },
    )
    receipt = invoke(service, session, "plan_task", command)
    frozen = invoke(service, session, "get_task_plan", receipt["resourceId"])
    assert frozen["steps"][0]["requestedMs"] == 5000
    assert frozen["maximumMicroCny"] == 1_200_000


def test_stale_input_and_expiry_reject_start(opened):
    import json

    from app.storage.settings import canonical
    from tests.tasks.test_executor import start

    service, directory, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    with connect(directory / "project.sqlite3") as db, db:
        draft = db.execute("SELECT id,payload_json FROM drafts").fetchone()
        changed = json.loads(draft["payload_json"])
        changed["content"]["brief"] = "changed"
        db.execute("UPDATE drafts SET payload_json=? WHERE id=?", (canonical(changed), draft["id"]))
    with pytest.raises(ProjectError, match="PLAN_STALE"):
        start(service, session, frozen)

    with connect(directory / "project.sqlite3") as db, db:
        db.execute(
            "UPDATE drafts SET payload_json=? WHERE id=?", (draft["payload_json"], draft["id"])
        )
        frozen["expiresAt"] = "2000-01-01T00:00:00+00:00"
        db.execute(
            "UPDATE task_plans SET plan_json=? WHERE id=?", (canonical(frozen), frozen["id"])
        )
    with pytest.raises(ProjectError, match="PLAN_STALE"):
        start(service, session, frozen)


def test_task_and_cost_uuid_cursor_survives_new_insertion(opened):
    from tests.tasks.test_executor import start, wait_task

    service, _, session = opened
    budget(service, session)
    for _ in range(2):
        frozen, _ = plan(service, session)
        receipt, _ = start(service, session, frozen)
        wait_task(service, session, receipt["resourceId"])
    first = invoke(service, session, "list_tasks", None, 1)
    assert first["nextCursor"] == first["items"][0]["id"]
    cost_first = invoke(service, session, "list_cost_entries", None, 1)
    assert cost_first["nextCursor"] == cost_first["items"][0]["callId"]
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    wait_task(service, session, receipt["resourceId"])
    second = invoke(service, session, "list_tasks", first["nextCursor"], 1)
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert second["nextCursor"] is None
    cost_second = invoke(service, session, "list_cost_entries", cost_first["nextCursor"], 1)
    assert cost_second["items"][0]["callId"] != cost_first["items"][0]["callId"]
    assert cost_second["nextCursor"] is None


def test_stage_configuration_change_invalidates_frozen_plan(opened):
    from tests.tasks.test_executor import start

    service, directory, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    with connect(directory / "project.sqlite3") as db, db:
        db.execute(
            "INSERT INTO stage_models VALUES(?,?,?)", ("story_adaptation", str(uuid4()), "new")
        )
    with pytest.raises(ProjectError, match="PLAN_STALE"):
        start(service, session, frozen)
