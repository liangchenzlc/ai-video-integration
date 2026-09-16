from pathlib import Path
from uuid import uuid4

import pytest
from app.main import create_app

from tests.api.test_runtime import client, make_context


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_project_http_creation_replay_open_and_window_binding(tmp_path: Path) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "app"
    app = create_app(context)
    directory = tmp_path / "我的项目"
    directory.mkdir()
    grant_id = str(uuid4())
    window = {"X-Window-Id": "1"}
    async with client(app) as http:
        registered = await http.post(
            "/api/v1/file-grants",
            headers=window,
            json={
                "clientOperationId": str(uuid4()),
                "expectedRevision": 0,
                "payload": {
                    "grantId": grant_id,
                    "path": str(directory),
                    "purpose": "createProject",
                    "windowId": 1,
                },
            },
        )
        assert registered.status_code == 200
        command = {
            "clientOperationId": str(uuid4()),
            "expectedRevision": 0,
            "payload": {
                "directoryGrantId": grant_id,
                "name": "新故事",
                "aspect": "16:9",
                "resolution": "1080p",
                "fps": {"numerator": 24, "denominator": 1},
                "targetMs": 30000,
            },
        }
        created = await http.post("/api/v1/projects", json=command, headers=window)
        assert created.status_code == 201
        assert str(tmp_path) not in created.text
        replayed = await http.post("/api/v1/projects", json=command, headers=window)
        assert replayed.status_code == 201
        assert replayed.json()["data"] == created.json()["data"]
        operation = await http.get(
            f"/api/v1/operations/{command['clientOperationId']}", headers=window
        )
        assert operation.json()["data"]["receipt"] == created.json()["data"]
        open_grant = str(uuid4())
        await http.post(
            "/api/v1/file-grants",
            headers=window,
            json={
                "clientOperationId": str(uuid4()),
                "expectedRevision": 0,
                "payload": {
                    "grantId": open_grant,
                    "path": str(directory),
                    "purpose": "openProject",
                    "windowId": 1,
                },
            },
        )
        opened = await http.post(
            "/api/v1/project-sessions",
            headers=window,
            json={"directoryGrantId": open_grant, "requestedMode": "write"},
        )
        assert opened.status_code == 201
        session = opened.json()["data"]
        assert session["project"]["name"] == "新故事"
        assert session["project"]["readOnly"] is False
        wrong_window = await http.get(
            f"/api/v1/projects/{session['projectId']}",
            headers={"X-Window-Id": "2", "X-Project-Session": session["projectSessionId"]},
        )
        assert wrong_window.status_code in (401, 403)
        recent = await http.get("/api/v1/recent-projects", headers=window)
        assert recent.status_code == 200
        assert recent.json()["data"][0]["projectId"] == session["projectId"]
        assert str(tmp_path) not in recent.text
        closed = await http.delete(
            f"/api/v1/project-sessions/{session['projectSessionId']}",
            headers=window,
        )
        assert closed.status_code == 200


@pytest.mark.anyio
async def test_project_entry_rejects_missing_or_duplicate_window_identity(tmp_path: Path) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "app"
    async with client(create_app(context)) as http:
        missing = await http.get("/api/v1/recent-projects")
        duplicated = await http.get(
            "/api/v1/recent-projects", headers=[("X-Window-Id", "1"), ("X-Window-Id", "2")]
        )
    assert missing.status_code == 400
    assert duplicated.status_code == 400
