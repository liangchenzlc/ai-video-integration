import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.api.v1.projects import ProjectStore
from app.api.v1.tasks_models import InputPreview
from app.main import create_app
from app.services.projects import ProjectService
from app.services.task_adapter import SyntheticAdapter
from pydantic import ValidationError

from tests.api.test_runtime import client, make_context
from tests.storage.test_drafts import open_session
from tests.storage.test_drafts import request as draft_request
from tests.storage.test_projects import command as project_command
from tests.storage.test_projects import grant
from tests.storage.test_task_plans import budget, plan
from tests.tasks.test_executor import start, wait_task


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_input_preview_rejects_private_fields_and_kind_mismatch() -> None:
    valid = InputPreview.model_validate({"kind": "story", "payload": {"sourceText": "draft"}})
    assert valid.payload == {"sourceText": "draft"}
    for payload in ({"privatePath": "sentinel"}, {"clips": []}, {"sourceText": 123}):
        with pytest.raises(ValidationError):
            InputPreview.model_validate({"kind": "story", "payload": payload})


@pytest.mark.anyio
async def test_task_candidate_route_returns_revision_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, task = (str(uuid4()) for _ in range(3))
    calls: list[tuple[Any, ...]] = []

    class Store:
        def list_task_candidates(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            return {"items": [], "nextCursor": None}

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    headers = {"X-Window-Id": "1", "X-Project-Session": session}
    async with client(create_app(context)) as http:
        response = await http.get(
            f"/api/v1/projects/{project}/tasks/{task}/candidates?limit=17", headers=headers
        )
    assert response.status_code == 200, (response.text, calls)
    assert response.json()["data"] == {"items": [], "nextCursor": None}
    assert calls == [(project, session, 1, task, None, 17)]


@pytest.mark.anyio
async def test_task_writes_validate_identity_money_and_disclosure_before_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, operation, plan = (str(uuid4()) for _ in range(4))
    calls: list[tuple[Any, ...]] = []

    class Store:
        def start_task(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            return {
                "operationId": operation,
                "resourceId": str(uuid4()),
                "committedRevision": 7,
                "state": "accepted",
            }

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    body = {
        "clientOperationId": operation,
        "expectedRevision": 6,
        "payload": {
            "planId": plan,
            "authorizedMaximumMicroCny": 1200000,
            "disclosureAccepted": True,
        },
    }
    headers = {"X-Window-Id": "1", "X-Project-Session": session}
    async with client(create_app(context)) as http:
        result = await http.post(f"/api/v1/projects/{project}/tasks", headers=headers, json=body)
        assert result.status_code == 202, result.text
        assert calls == [(project, session, 1, body)]
        for invalid in (-1, 1.5, True, "1200000", 9007199254740992):
            candidate = {
                **body,
                "payload": {**body["payload"], "authorizedMaximumMicroCny": invalid},
            }
            rejected = await http.post(
                f"/api/v1/projects/{project}/tasks", headers=headers, json=candidate
            )
            assert rejected.status_code == 422
        missing = await http.post(
            f"/api/v1/projects/{project}/tasks", headers={"X-Window-Id": "1"}, json=body
        )
        assert missing.status_code == 401
        assert len(calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("suffix", ["tasks", "cost-entries"])
async def test_task_pagination_allows_only_bounded_unique_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, cursor = (str(uuid4()) for _ in range(3))
    received: list[tuple[int, str | None]] = []

    class Store:
        def list_tasks(self, *args: Any, limit: int, cursor: str | None) -> dict[str, Any]:
            assert args == (project, session, 4)
            received.append((limit, cursor))
            return {"items": [], "nextCursor": None}

        list_cost_entries = list_tasks

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    headers = {"X-Window-Id": "4", "X-Project-Session": session}
    base = f"/api/v1/projects/{project}/{suffix}"
    async with client(create_app(context)) as http:
        valid = await http.get(base + f"?limit=50&cursor={cursor}", headers=headers)
        assert valid.status_code == 200, valid.text
        assert received == [(50, cursor)]
        for query in ("limit=201", "limit=1&limit=2", "cursor=nope", "offset=1", "limit=-1"):
            rejected = await http.get(base + "?" + query, headers=headers)
            assert rejected.status_code == 422
        assert len(received) == 1


@pytest.mark.anyio
async def test_task_activity_does_not_allow_private_path_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    leak = False

    class Store:
        def get_task_activity(self) -> list[dict[str, Any]]:
            result = {
                "projectId": str(uuid4()),
                "projectName": "Local example",
                "taskId": str(uuid4()),
                "state": "result_unknown",
            }
            if leak:
                result["directory"] = "PRIVATE-PATH-SENTINEL"
            return [result]

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    async with client(create_app(context)) as http:
        result = await http.get("/api/v1/task-activity", headers={"X-Window-Id": "1"})
        assert result.status_code == 200, result.text
        assert result.json()["data"][0]["state"] == "result_unknown"
        leak = True
        failed = await http.get("/api/v1/task-activity", headers={"X-Window-Id": "1"})
        assert failed.status_code == 500
        assert "PRIVATE-PATH-SENTINEL" not in failed.text


@pytest.mark.anyio
@pytest.mark.parametrize("lost_response", [False, True])
async def test_persisted_task_lifecycle_and_original_operation_recovery_over_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_response: bool
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "application"
    service = ProjectService(context.app_data_dir)
    monkeypatch.setattr(ProjectStore, "get", lambda _: service)
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(project_command(grant(service, directory, "createProject")), 1)
    session = open_session(service, directory)
    pid, sid = session["projectId"], session["projectSessionId"]
    headers = {"X-Window-Id": "1", "X-Project-Session": sid}
    base = f"/api/v1/projects/{pid}"

    class Adapter(SyntheticAdapter):
        submits = 0

        def submit(self, request: dict[str, Any], submission_token: str) -> dict[str, Any]:
            self.submits += 1
            if lost_response:
                raise TimeoutError("PRIVATE-PROVIDER-ERROR-SENTINEL")
            return super().submit(request, submission_token)

    adapter = Adapter()
    service._tasks.adapter = adapter

    def command(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "clientOperationId": str(uuid4()),
            "expectedRevision": service.get_project(pid, sid, 1)["revision"],
            "payload": payload,
        }

    try:
        async with client(create_app(context)) as http:
            budget = await http.put(
                base + "/budget",
                headers=headers,
                json=command(
                    {
                        "totalMicroCny": 10_000_000,
                        "allocations": [{"stage": "story", "limitMicroCny": 10_000_000}],
                        "warningPercent": 80,
                    }
                ),
            )
            assert budget.status_code == 200, budget.text
            draft = draft_request({}, revision=service.get_project(pid, sid, 1)["revision"])
            draft_path = base + "/drafts/" + draft["payload"]["draftId"]
            saved = await http.put(draft_path, headers=headers, json=draft)
            assert saved.status_code == 200, saved.text
            plan_payload = {
                "objectId": draft["payload"]["artifactId"],
                "stage": "story",
                "phase": "story_adaptation",
                "goal": "Adapt this story",
                "inputRevisionIds": [],
                "candidates": 1,
                "includePrecheck": False,
                "executionMode": "synthetic",
            }
            incomplete = await http.post(
                base + "/task-plans", headers=headers, json=command(plan_payload)
            )
            assert incomplete.status_code == 422, incomplete.text
            assert incomplete.json()["error"]["code"] == "INPUT_INCOMPLETE"
            draft["clientOperationId"] = str(uuid4())
            draft["expectedRevision"] = service.get_project(pid, sid, 1)["revision"]
            draft["payload"]["content"]["content"] = {
                "sourceText": "完整故事原文",
                "brief": "改编成短片",
            }
            saved = await http.put(draft_path, headers=headers, json=draft)
            assert saved.status_code == 200, saved.text
            planned = await http.post(
                base + "/task-plans", headers=headers, json=command(plan_payload)
            )
            assert planned.status_code == 200, planned.text
            plan_id = planned.json()["data"]["resourceId"]
            frozen = await http.get(base + "/task-plans/" + plan_id, headers=headers)
            assert frozen.status_code == 200, frozen.text
            plan = frozen.json()["data"]
            assert plan["inputPreview"]["payload"]["sourceText"] == "完整故事原文"
            assert adapter.submits == 0
            start_command = command(
                {
                    "planId": plan_id,
                    "authorizedMaximumMicroCny": plan["maximumMicroCny"],
                    "disclosureAccepted": True,
                }
            )
            started = await http.post(base + "/tasks", headers=headers, json=start_command)
            assert started.status_code == 202, started.text
            receipt = started.json()["data"]
            replay = await http.post(base + "/tasks", headers=headers, json=start_command)
            assert replay.json()["data"] == receipt
            operation = await http.get(
                base + "/operations/" + start_command["clientOperationId"], headers=headers
            )
            assert operation.status_code == 200, operation.text
            assert operation.json()["data"]["receipt"] == receipt
            task_path = base + "/tasks/" + receipt["resourceId"]
            for _ in range(200):
                observed = await http.get(task_path, headers=headers)
                assert observed.status_code == 200, observed.text
                task = observed.json()["data"]
                if task["state"] not in {"pending", "running"}:
                    break
                await asyncio.sleep(0.01)
            assert task["state"] == ("result_unknown" if lost_response else "complete")
            assert adapter.submits == 1
            call_path = base + "/calls/" + task["callIds"][0]
            call = await http.get(call_path, headers=headers)
            assert call.status_code == 200, call.text
            assert call.json()["data"]["providerId"] == "synthetic-local"
            assert "PRIVATE-PROVIDER-ERROR-SENTINEL" not in call.text
            listed = await http.get(base + "/tasks?limit=50", headers=headers)
            assert listed.status_code == 200, listed.text
            assert listed.json()["data"]["items"][0]["id"] == task["id"]
            if lost_response:
                stopped = await http.post(
                    call_path + "/recovery",
                    headers=headers,
                    json=command({"action": "stop_waiting"}),
                )
                assert stopped.status_code == 202, stopped.text
            else:
                settlement = command(
                    {
                        "settledMicroCny": 90_000,
                        "basis": "Fixture invoice",
                        "evidenceMediaIds": [],
                        "reason": "Initial fixture settlement",
                    }
                )
                settled = await http.post(
                    call_path + "/settlements", headers=headers, json=settlement
                )
                assert settled.status_code == 200, settled.text
                again = await http.post(
                    call_path + "/settlements", headers=headers, json=settlement
                )
                assert again.json()["data"] == settled.json()["data"]
            summary = await http.get(base + "/cost-summary", headers=headers)
            assert summary.status_code == 200, summary.text
            assert summary.json()["data"]["reservedMicroCny"] == (100_000 if lost_response else 0)
            assert summary.json()["data"]["settledMicroCny"] == (0 if lost_response else 90_000)
            entries = await http.get(base + "/cost-entries?limit=50", headers=headers)
            assert entries.status_code == 200, entries.text
            assert len(entries.json()["data"]["items"]) == 1
            denied = await http.get(task_path, headers={**headers, "X-Window-Id": "2"})
            assert denied.status_code in {401, 403}
            assert adapter.submits == 1
    finally:
        service.close()


@pytest.mark.anyio
async def test_persisted_task_and_cost_pagination_round_trips_uuid_cursors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "application"
    service = ProjectService(context.app_data_dir)
    monkeypatch.setattr(ProjectStore, "get", lambda _: service)
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(project_command(grant(service, directory, "createProject")), 1)
    session = open_session(service, directory)
    headers = {"X-Window-Id": "1", "X-Project-Session": session["projectSessionId"]}
    base = f"/api/v1/projects/{session['projectId']}"
    try:
        budget(service, session)
        task_ids, call_ids = set(), set()
        for _ in range(3):
            frozen, _command = plan(service, session)
            receipt, _command = start(service, session, frozen)
            task = wait_task(service, session, receipt["resourceId"])
            assert task["state"] == "complete"
            task_ids.add(task["id"])
            call_ids.update(task["callIds"])
        async with client(create_app(context)) as http:
            for suffix, id_field, expected in (
                ("tasks", "id", task_ids),
                ("cost-entries", "callId", call_ids),
            ):
                cursor = None
                seen: list[str] = []
                for _ in range(4):
                    query = "?limit=1" + ("&cursor=" + cursor if cursor else "")
                    response = await http.get(base + "/" + suffix + query, headers=headers)
                    assert response.status_code == 200, response.text
                    page = response.json()["data"]
                    seen.extend(item[id_field] for item in page["items"])
                    cursor = page["nextCursor"]
                    if cursor is None:
                        break
                assert set(seen) == expected
                assert len(seen) == 3
                assert cursor is None
    finally:
        service.close()
