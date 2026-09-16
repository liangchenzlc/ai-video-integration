import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from app.api.v1.projects import ProjectStore
from app.main import create_app
from app.services.projects import ProjectService

from tests.api.test_runtime import client, make_context
from tests.storage.test_media import FFMPEG, fixture_media, mutation
from tests.storage.test_projects import command, grant


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_media_http_tools_import_job_preview_and_pagination(
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
    headers = {"X-Window-Id": "1", "X-Project-Session": session["projectSessionId"]}
    base = f"/api/v1/projects/{session['projectId']}"
    try:
        async with client(app) as http:
            configured = await http.put(
                "/api/v1/settings/media-tools",
                headers=headers,
                json=mutation(0, ffmpegGrantId=grant(service, FFMPEG, "ffmpeg")),
            )
            assert configured.status_code == 200, configured.text
            settings = await http.get("/api/v1/settings", headers=headers)
            assert settings.json()["data"]["ffmpegConfigured"] is True
            assert str(FFMPEG) not in settings.text
            source = fixture_media(tmp_path / "source.png")
            request = mutation(
                session["project"]["revision"],
                fileGrantId=grant(service, source, "importMedia"),
                purpose="reference",
            )
            accepted = await http.post(base + "/imports", headers=headers, json=request)
            assert accepted.status_code == 202, accepted.text
            receipt = accepted.json()["data"]
            replay = await http.post(base + "/imports", headers=headers, json=request)
            assert replay.json()["data"] == receipt
            job: dict[str, Any] = {}
            for _ in range(200):
                response = await http.get(base + "/jobs/" + receipt["resourceId"], headers=headers)
                assert response.status_code == 200, response.text
                job = response.json()["data"]
                if job["state"] in {"failed", "succeeded", "cancelled"}:
                    break
                await asyncio.sleep(0.05)
            assert job["state"] == "succeeded", job
            jobs = await http.get(base + "/jobs", headers=headers)
            assert jobs.json()["data"][0]["id"] == job["id"]
            media = await http.get(base + "/media?limit=1", headers=headers)
            assert media.status_code == 200, media.text
            assert media.json()["data"]["items"][0]["id"] == job["resultId"]
            path = base + "/media/" + job["resultId"]
            metadata = await http.get(path + "/metadata", headers=headers)
            assert metadata.status_code == 200
            assert str(tmp_path) not in json.dumps(metadata.json())
            full = await http.get(path, headers=headers)
            assert full.status_code == 200 and full.content == source.read_bytes()
            part = await http.get(path, headers={**headers, "Range": "bytes=1-5"})
            assert part.status_code == 206 and part.content == source.read_bytes()[1:6]
            wrong_window = await http.get(path, headers={**headers, "X-Window-Id": "2"})
            assert wrong_window.status_code in {401, 403}
            for query in ("limit=1&limit=2", "unknown=1", "cursor=not-an-id", "limit=201"):
                assert (
                    await http.get(base + "/media?" + query, headers=headers)
                ).status_code == 422
    finally:
        service.close()
