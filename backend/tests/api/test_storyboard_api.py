from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.api.v1.projects import ProjectStore
from app.main import create_app

from tests.api.test_runtime import client, make_context


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_storyboard_routes_bind_session_and_preserve_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, shot, operation = (str(uuid4()) for _ in range(4))
    calls: list[tuple[Any, ...]] = []

    class Store:
        def get_storyboard(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            return {"drafts": [], "shotIds": []}

        def get_coverage(self, *args: Any) -> dict[str, Any]:
            return {
                "unassignedRequirementIds": [],
                "unresolvedRequirementIds": [],
                "invalidReferenceIds": [],
            }

        def reorder_shots(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            return {
                "operationId": operation,
                "resourceId": project,
                "state": "committed",
                "committedRevision": 2,
            }

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    prompt_requests: list[tuple[Any, ...]] = []

    def preview(*args: Any) -> dict[str, Any]:
        prompt_requests.append(args[1:])
        return {
            "templateId": "shot-image",
            "templateVersion": "fixture",
            "prompt": "",
            "sourceRevisionIds": [],
            "blockers": ["Not production ready"],
            "reusableVideoMediaId": None,
        }

    monkeypatch.setattr("app.api.v1.storyboard.preview_for_project", preview)
    headers = {"X-Window-Id": "1", "X-Project-Session": session}
    base = f"/api/v1/projects/{project}"
    command = {
        "clientOperationId": operation,
        "expectedRevision": 1,
        "payload": {"shotIds": [shot]},
    }
    async with client(create_app(context)) as http:
        assert (await http.get(base + "/storyboard", headers=headers)).status_code == 200
        assert (await http.get(base + "/coverage", headers=headers)).status_code == 200
        prompt_route = base + f"/storyboard/shots/{shot}/prompt"
        assert (await http.get(prompt_route + "?phase=image", headers=headers)).status_code == 200
        assert (
            await http.get(prompt_route + "?phase=image&phase=video", headers=headers)
        ).status_code == 422
        result = await http.put(base + "/shot-order", headers=headers, json=command)
        assert result.status_code == 200, result.text
        invalid = {**command, "payload": {"shotIds": [shot, shot]}}
        assert (
            await http.put(base + "/shot-order", headers=headers, json=invalid)
        ).status_code == 422
        assert (
            await http.get(base + "/storyboard", headers={"X-Window-Id": "1"})
        ).status_code == 401
    assert calls == [(project, session, 1), (project, session, 1, command)]
    assert prompt_requests == [(project, session, 1, shot, "image")]


@pytest.mark.anyio
async def test_reference_verification_rejects_invalid_purpose_before_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, draft, media, operation = (str(uuid4()) for _ in range(5))
    received: list[tuple[Any, ...]] = []

    class Store:
        def verify_reference(self, *args: Any) -> dict[str, Any]:
            received.append(args)
            return {
                "operationId": operation,
                "resourceId": draft,
                "state": "committed",
                "committedRevision": 2,
            }

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    body = {
        "clientOperationId": operation,
        "expectedRevision": 1,
        "payload": {
            "draftId": draft,
            "mediaId": media,
            "role": "firstFrame",
            "matchesPurpose": False,
            "note": "The action is already complete.",
        },
    }
    headers = {"X-Window-Id": "1", "X-Project-Session": session}
    route = f"/api/v1/projects/{project}/references/verification"
    async with client(create_app(context)) as http:
        result = await http.post(route, headers=headers, json=body)
        assert result.status_code == 200, result.text
        body["payload"]["role"] = "unrecognized"
        assert (await http.post(route, headers=headers, json=body)).status_code == 422
    assert len(received) == 1
    assert received[0][3]["payload"]["matchesPurpose"] is False
