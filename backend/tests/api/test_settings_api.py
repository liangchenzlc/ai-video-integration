from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.api.v1.projects import ProjectStore
from app.main import create_app
from app.services.projects import ProjectService
from app.storage.errors import ProjectError

from tests.api.test_runtime import client, make_context
from tests.storage.test_capabilities import profile
from tests.storage.test_projects import command as project_command
from tests.storage.test_projects import grant

SECRET = "sentinel-never-return-or-log-this-secret"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def command(payload: dict[str, Any]) -> dict[str, Any]:
    return {"clientOperationId": str(uuid4()), "expectedRevision": 0, "payload": payload}


@pytest.mark.anyio
async def test_credential_route_validates_secret_without_echo_and_preserves_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    calls: list[tuple[str, dict[str, Any], int]] = []

    class Store:
        def set_credential(self, provider: str, value: dict[str, Any], window: int) -> Any:
            calls.append((provider, value, window))
            if len(calls) == 2:
                raise ProjectError("CREDENTIAL_ENCRYPTION_FAILED", 503)
            return {
                "operationId": value["clientOperationId"],
                "resourceId": str(uuid4()),
                "committedRevision": 1,
                "state": "committed",
            }

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    request = command({"secret": {"kind": "api_key", "apiKey": SECRET}, "persistence": "dpapi"})
    async with client(create_app(context)) as http:
        response = await http.put(
            "/api/v1/credentials/bailian", headers={"X-Window-Id": "3"}, json=request
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["operationId"] == request["clientOperationId"]
        assert calls == [("bailian", request, 3)]
        failed = await http.put(
            "/api/v1/credentials/bailian", headers={"X-Window-Id": "3"}, json=request
        )
        assert failed.json()["error"]["code"] == "CREDENTIAL_ENCRYPTION_FAILED"
        invalid = command(
            {
                "secret": {"kind": "api_key", "apiKey": SECRET, "path": SECRET},
                "persistence": "plain",
            }
        )
        rejected = await http.put(
            "/api/v1/credentials/bailian", headers={"X-Window-Id": "3"}, json=invalid
        )
        assert rejected.status_code == 422
        no_window = await http.put("/api/v1/credentials/bailian", json=request)
        assert no_window.status_code == 400
        unsupported = await http.put(
            "/api/v1/credentials/bad%20provider", headers={"X-Window-Id": "3"}, json=request
        )
        assert unsupported.status_code == 422
        assert len(calls) == 2
        assert all(
            SECRET not in result.text
            for result in [response, failed, rejected, no_window, unsupported]
        )
        assert SECRET not in caplog.text


@pytest.mark.anyio
async def test_safe_settings_details_reject_unknown_secret_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    leak = False

    class Store:
        def get_settings_details(self) -> dict[str, Any]:
            data: dict[str, Any] = {"credentials": [], "storageProfiles": [], "toolSummary": None}
            if leak:
                data["secret"] = SECRET
            return data

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    async with client(create_app(context)) as http:
        response = await http.get("/api/v1/settings/details", headers={"X-Window-Id": "1"})
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "credentials": [],
            "storageProfiles": [],
            "toolSummary": None,
        }
        leak = True
        rejected = await http.get("/api/v1/settings/details", headers={"X-Window-Id": "1"})
        assert rejected.status_code == 500
        assert SECRET not in rejected.text


@pytest.mark.anyio
async def test_session_credentials_storage_receipt_and_restart_through_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "application"
    service = ProjectService(context.app_data_dir)
    monkeypatch.setattr(ProjectStore, "get", lambda _: service)
    headers = {"X-Window-Id": "1"}
    request = command(
        {
            "secret": {
                "kind": "oss",
                "accessKeyId": "test-access-id",
                "accessKeySecret": SECRET,
                "securityToken": None,
            },
            "persistence": "session_only",
        }
    )
    try:
        async with client(create_app(context)) as http:
            saved = await http.put("/api/v1/credentials/oss", headers=headers, json=request)
            assert saved.status_code == 200, saved.text
            receipt = saved.json()["data"]
            retry = await http.put("/api/v1/credentials/oss", headers=headers, json=request)
            assert retry.json()["data"] == receipt
            details = await http.get("/api/v1/settings/details", headers=headers)
            assert details.json()["data"]["credentials"][0]["id"] == receipt["resourceId"]
            profile = command(
                {
                    "providerId": "oss",
                    "region": "cn-hangzhou",
                    "bucket": "my-audio-bucket",
                    "credentialRef": receipt["resourceId"],
                    "retentionHours": 48,
                }
            )
            profile["expectedRevision"] = receipt["committedRevision"]
            configured = await http.put("/api/v1/settings/storage", headers=headers, json=profile)
            assert configured.status_code == 200, configured.text
            details = await http.get("/api/v1/settings/details", headers=headers)
            assert details.json()["data"]["storageProfiles"][0]["persistence"] == "session_only"
            current = await http.get("/api/v1/settings", headers=headers)
            assert current.json()["data"]["revision"] == 2
            assert current.json()["data"]["providers"][0]["credentialConfigured"] is True
            operation = await http.get(
                "/api/v1/operations/" + request["clientOperationId"], headers=headers
            )
            assert operation.status_code == 200, operation.text
            assert operation.json()["data"]["receipt"] == receipt
            assert all(
                SECRET not in response.text
                for response in [saved, retry, details, current, operation]
            )
        service.close()
        service = ProjectService(context.app_data_dir)
        async with client(create_app(context)) as http:
            reopened = await http.get("/api/v1/settings/details", headers=headers)
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["data"]["credentials"] == []
            assert reopened.json()["data"]["storageProfiles"] == []
        for path in context.app_data_dir.iterdir():
            if path.is_file():
                assert SECRET.encode() not in path.read_bytes()
    finally:
        service.close()


@pytest.mark.anyio
async def test_free_check_receipt_job_and_capability_states_survive_http_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    capability = profile()
    calls: list[str] = []

    def checker(_profile: dict[str, Any], _secret: dict[str, Any]) -> bool:
        calls.append("free metadata fixture")
        return True

    service = ProjectService(
        tmp_path, capability_profiles=[capability], free_checkers={capability["id"]: checker}
    )
    monkeypatch.setattr(ProjectStore, "get", lambda _: service)
    headers = {"X-Window-Id": "1"}
    try:
        async with client(create_app(context)) as http:
            saved = await http.put(
                "/api/v1/credentials/fixture",
                headers=headers,
                json=command(
                    {"secret": {"kind": "api_key", "apiKey": SECRET}, "persistence": "session_only"}
                ),
            )
            assert saved.status_code == 200
            request = command({"capabilityId": capability["id"]})
            request["expectedRevision"] = saved.json()["data"]["committedRevision"]
            checked = await http.post("/api/v1/connection-checks", headers=headers, json=request)
            assert checked.status_code == 202, checked.text
            replay = await http.post("/api/v1/connection-checks", headers=headers, json=request)
            assert replay.json()["data"] == checked.json()["data"]
            assert len(calls) == 1
            result = await http.get(
                "/api/v1/jobs/" + checked.json()["data"]["resourceId"], headers=headers
            )
            assert result.status_code == 200 and result.json()["data"]["state"] == "succeeded"
            settings = await http.get("/api/v1/settings", headers=headers)
            assert settings.status_code == 200, settings.text
            state = settings.json()["data"]["capabilities"][0]
            assert state["accountState"] == "available"
            assert state["interfaceState"] == "verified"
            assert state["qualityState"] == "unverified"
            assert SECRET not in settings.text
    finally:
        service.close()


@pytest.mark.anyio
async def test_stage_models_require_owned_session_and_global_check_does_not_infer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "application"
    service = ProjectService(context.app_data_dir)
    monkeypatch.setattr(ProjectStore, "get", lambda _: service)
    folder = tmp_path / "project"
    folder.mkdir()
    service.create_project(project_command(grant(service, folder, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, folder, "openProject"), "requestedMode": "write"}, 1
    )
    headers = {"X-Window-Id": "1", "X-Project-Session": session["projectSessionId"]}
    path = f"/api/v1/projects/{session['projectId']}/stage-models"
    try:
        async with client(create_app(context)) as http:
            read = await http.get(path, headers=headers)
            assert read.status_code == 200, read.text
            assert read.json()["data"] == []
            unauthorized = await http.get(path, headers={**headers, "X-Window-Id": "2"})
            assert unauthorized.status_code in {401, 403}
            missing_session = await http.put(
                path,
                headers={"X-Window-Id": "1"},
                json=command({"phase": "story_outline", "capabilityId": str(uuid4())}),
            )
            assert missing_session.status_code == 401
            invalid_phase = await http.put(
                path,
                headers=headers,
                json=command({"phase": "story", "capabilityId": str(uuid4())}),
            )
            assert invalid_phase.status_code == 422
            unknown_check = await http.post(
                "/api/v1/connection-checks",
                headers=headers,
                json=command({"capabilityId": str(uuid4())}),
            )
            assert unknown_check.status_code == 422
            assert unknown_check.json()["error"]["code"] == "CONNECTION_CHECK_UNAVAILABLE"
            job = await http.get("/api/v1/jobs/" + str(uuid4()), headers=headers)
            assert job.status_code == 404, job.text
            rejected_delete = await http.post(
                "/api/v1/credentials/missing/delete",
                headers=headers,
                json=command({"confirmed": False}),
            )
            assert rejected_delete.status_code in {409, 422}
            assert service.get_tool_settings()["revision"] == 0
    finally:
        service.close()
