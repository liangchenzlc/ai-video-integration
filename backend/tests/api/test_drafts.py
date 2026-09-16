from pathlib import Path
from uuid import uuid4

import pytest
from app.api.v1.projects import ProjectStore
from app.main import create_app
from app.services.projects import ProjectService

from tests.api.test_runtime import client, make_context
from tests.storage.test_projects import command, grant


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_draft_http_preserves_large_partial_and_empty_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "app"
    app = create_app(context)
    service = ProjectService(context.app_data_dir)
    monkeypatch.setattr(ProjectStore, "get", lambda _self: service)
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    project_id = session["projectId"]
    draft_id = str(uuid4())
    headers = {"X-Window-Id": "1", "X-Project-Session": session["projectSessionId"]}
    path = f"/api/v1/projects/{project_id}/drafts/{draft_id}"
    request = {
        "clientOperationId": str(uuid4()),
        "expectedRevision": session["project"]["revision"],
        "payload": {
            "draftId": draft_id,
            "artifactId": str(uuid4()),
            "baseRevisionId": None,
            "content": {"kind": "story", "content": {"sourceText": "故事\r\n" * 20000}},
        },
    }
    try:
        async with client(app) as http:
            saved = await http.put(path, headers=headers, json=request)
            assert saved.status_code == 200, saved.text
            receipt = saved.json()["data"]
            fetched = await http.get(path, headers=headers)
            assert fetched.status_code == 200
            assert fetched.json()["data"]["content"]["content"]["sourceText"] == "故事\r\n" * 20000
            assert str(tmp_path) not in fetched.text
            replay = await http.put(path, headers=headers, json=request)
            assert replay.json()["data"] == receipt
            operation = await http.get(
                f"/api/v1/projects/{project_id}/operations/{request['clientOperationId']}",
                headers=headers,
            )
            assert operation.json()["data"]["receipt"] == receipt
            listed = await http.get(f"/api/v1/projects/{project_id}/drafts", headers=headers)
            assert listed.json()["data"][0]["id"] == draft_id
            assert "sourceText" not in listed.text
            denied = await http.get(path, headers={**headers, "X-Window-Id": "2"})
            assert denied.status_code in (401, 403)
            mismatch = await http.put(
                path.replace(draft_id, str(uuid4())), headers=headers, json=request
            )
            assert mismatch.status_code == 400
            request["clientOperationId"] = str(uuid4())
            request["expectedRevision"] = receipt["committedRevision"]
            request["payload"]["content"]["content"] = {"sourceText": "", "brief": ""}
            assert (await http.put(path, headers=headers, json=request)).status_code == 200
            empty = await http.get(path, headers=headers)
            assert empty.json()["data"]["content"]["content"]["sourceText"] == ""
    finally:
        service.close()
