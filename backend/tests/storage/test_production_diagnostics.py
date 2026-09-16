"""T13 basic diagnostic privacy, native grants, replay and project binding."""

import json
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.api.v1.projects import ProjectStore
from app.main import create_app
from app.services.projects import ProjectService
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.api.test_runtime import client, make_context
from tests.storage.test_drafts import opened as opened
from tests.storage.test_drafts import request, save
from tests.storage.test_projects import grant
from tests.storage.test_versions import adopt, candidate, command, current

Json = dict[str, Any]
Opened = tuple[ProjectService, Path, Json]


def diagnostic_command(opened: Opened, target: Path, *, content: bool = False) -> Json:
    service, _, session = opened
    return command(
        0,
        {
            "projectId": session["projectId"] if content else None,
            "includeProject": content,
            "includeContent": content,
            "targetGrantId": grant(service, target, "diagnostic"),
        },
    )


def archive_text(target: Path) -> tuple[list[str], str]:
    with zipfile.ZipFile(target) as archive:
        return archive.namelist(), "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )


def test_default_diagnostic_works_without_project_and_replays_once(
    opened: Opened, tmp_path: Path
) -> None:
    service, _, session = opened
    save(
        service,
        session,
        request({"sourceText": "PRIVATE_STORY_SENTINEL"}, revision=current(opened)),
    )
    target = tmp_path / "diagnostic.zip"
    body = diagnostic_command(opened, target)
    service.close_session(session["projectSessionId"], 1)
    preview = service._diagnostics.preview(
        1,
        {
            "projectId": None,
            "includeProject": False,
            "includeContent": False,
        },
    )
    assert [item["name"] for item in preview["files"]] == ["runtime.json"]
    receipt = service._diagnostics.create(1, body)
    original = target.read_bytes()
    assert service._diagnostics.create(1, body) == receipt
    assert target.read_bytes() == original
    names, text = archive_text(target)
    assert names == ["runtime.json"]
    assert "PRIVATE_STORY_SENTINEL" not in text and str(tmp_path) not in text
    assert service.get_global_job(receipt["resourceId"])["state"] == "succeeded"
    with connect(service._application, "ro") as db:
        assert (
            db.execute("SELECT count(*) FROM global_jobs WHERE kind='diagnostic'").fetchone()[0]
            == 1
        )


def test_explicit_content_redacts_configured_and_quoted_secrets(
    opened: Opened, tmp_path: Path
) -> None:
    service, _, session = opened
    service._settings.set_credential(
        "diagnostic-test",
        command(
            0,
            {
                "secret": {"kind": "api_key", "apiKey": "CONFIGURED_SENTINEL"},
                "persistence": "session_only",
            },
        ),
    )
    source = (
        'KEEP_CREATIVE_TEXT CONFIGURED_SENTINEL {"password":"QUOTED_JSON_SENTINEL"} '
        'api_key="QUOTED_INI_SENTINEL" Bearer TOKEN_SENTINEL '
        "https://example.invalid/media?signature=URL_SENTINEL\nC:\\private\\PATH_SENTINEL.wav"
    )
    save(service, session, request({"sourceText": source}, revision=current(opened)))
    target = tmp_path / "content.zip"
    receipt = service._diagnostics.create(
        1, diagnostic_command(opened, target, content=True), session["projectSessionId"]
    )
    assert service.get_global_job(receipt["resourceId"])["state"] == "succeeded"
    names, text = archive_text(target)
    assert set(names) == {"runtime.json", "project-summary.json", "content.json"}
    assert "KEEP_CREATIVE_TEXT" in text
    for marker in (
        "CONFIGURED_SENTINEL",
        "QUOTED_JSON_SENTINEL",
        "QUOTED_INI_SENTINEL",
        "TOKEN_SENTINEL",
        "URL_SENTINEL",
        "PATH_SENTINEL",
    ):
        assert marker not in text


def test_diagnostic_rejects_cross_project_or_expired_session(
    opened: Opened, tmp_path: Path
) -> None:
    service, _, session = opened
    target = tmp_path / "bound.zip"
    body = diagnostic_command(opened, target, content=True)
    with pytest.raises(ProjectError, match="SESSION_EXPIRED"):
        service._diagnostics.create(1, body)
    with pytest.raises(ProjectError, match="SESSION_EXPIRED"):
        service._diagnostics.create(2, body, session["projectSessionId"])
    body["payload"]["projectId"] = str(uuid4())
    with pytest.raises(ProjectError, match="SESSION_EXPIRED"):
        service._diagnostics.create(1, body, session["projectSessionId"])
    body["payload"]["projectId"] = session["projectId"]
    service.close_session(session["projectSessionId"], 1)
    with pytest.raises(ProjectError, match="SESSION_EXPIRED"):
        service._diagnostics.create(1, body, session["projectSessionId"])
    assert not target.exists()


def test_diagnostic_target_never_overwrites_and_failure_cleans_temporary(
    opened: Opened, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, _ = opened
    target = tmp_path / "existing.zip"
    target.write_bytes(b"original")
    with pytest.raises(ProjectError, match="TARGET_EXISTS"):
        service._diagnostics.create(1, diagnostic_command(opened, target))
    assert target.read_bytes() == b"original"
    target = tmp_path / "failed.zip"
    body = diagnostic_command(opened, target)
    wrong_grant = command(
        0, dict(body["payload"], targetGrantId=grant(service, tmp_path / "film.mp4", "exportFilm"))
    )
    with pytest.raises(ProjectError, match="GRANT_REJECTED"):
        service._diagnostics.create(1, wrong_grant)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("Injected destination failure")

    monkeypatch.setattr("app.services.diagnostics.os.rename", fail)
    receipt = service._diagnostics.create(1, body)
    assert service.get_global_job(receipt["resourceId"])["state"] == "failed"
    assert not target.exists()
    assert not list(tmp_path.glob(".avi-diagnostic-*.tmp"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_production_http_pages_fit_bridge_limit_and_diagnostics_bind_session(
    opened: Opened, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, session = opened
    expected = set()
    for _ in range(4):
        artifact, revision = candidate(opened, text="字" * 100000)
        adopt(opened, artifact, revision)
        expected.add(revision)
    monkeypatch.setattr(ProjectStore, "get", lambda self: service)
    context = make_context()
    context.app_data_dir = tmp_path / "app"
    headers = {"X-Window-Id": "1", "X-Project-Session": session["projectSessionId"]}
    async with client(create_app(context)) as http:
        offset, pages, found = 0, 0, set()
        while True:
            result = await http.get(
                f"/api/v1/projects/{session['projectId']}/production?offset={offset}",
                headers=headers,
            )
            assert result.status_code == 200, result.text[:200]
            assert len(result.content) < 1048576
            page = result.json()["data"]
            found.update(row["revisionId"] for row in page["adopted"])
            pages += 1
            if page["nextOffset"] is None:
                break
            assert page["nextOffset"] > offset
            offset = page["nextOffset"]
        assert pages >= 2 and found == expected
        options = {
            "projectId": session["projectId"],
            "includeProject": True,
            "includeContent": False,
        }
        missing = await http.post(
            "/api/v1/diagnostics/preview", headers={"X-Window-Id": "1"}, json=options
        )
        assert missing.status_code == 401
        preview = await http.post("/api/v1/diagnostics/preview", headers=headers, json=options)
        assert preview.status_code == 200
        assert len(preview.json()["data"]["files"]) == 2
        assert str(tmp_path) not in json.dumps(preview.json())
