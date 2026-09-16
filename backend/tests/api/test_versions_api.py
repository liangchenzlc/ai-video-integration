from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.api.v1.projects import ProjectStore
from app.main import create_app
from app.services.projects import ProjectService

from tests.api.test_runtime import client, make_context
from tests.storage.test_drafts import open_session
from tests.storage.test_drafts import request as draft_request
from tests.storage.test_projects import command as project_command
from tests.storage.test_projects import grant


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_version_preview_is_explicit_read_with_owned_identity_and_strict_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, artifact, revision, preview = (str(uuid4()) for _ in range(5))
    calls: list[tuple[Any, ...]] = []

    class Store:
        def preview_adoption(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            return {
                "previewId": preview,
                "artifactId": artifact,
                "fromRevisionId": None,
                "toRevisionId": revision,
                "affectedArtifactIds": [],
                "affectedScopes": [],
                "estimatedExtraMicroCny": None,
                "requiredChecks": ["structural", "references"],
                "expiresAt": "2026-09-16T06:00:00Z",
            }

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    headers = {"X-Window-Id": "3", "X-Project-Session": session}
    path = f"/api/v1/projects/{project}/artifacts/{artifact}/adoption-preview"
    payload = {"toRevisionId": revision, "expectedRevision": 7}
    async with client(create_app(context)) as http:
        result = await http.post(path, headers=headers, json=payload)
        assert result.status_code == 200, result.text
        assert calls == [(project, session, 3, artifact, payload)]
        assert result.json()["data"]["estimatedExtraMicroCny"] is None
        for value in (-1, True, "7", 1.5):
            rejected = await http.post(
                path, headers=headers, json={**payload, "expectedRevision": value}
            )
            assert rejected.status_code == 422, rejected.text
        missing = await http.post(path, headers={"X-Window-Id": "3"}, json=payload)
        assert missing.status_code == 401
        assert len(calls) == 1


@pytest.mark.anyio
async def test_create_revision_and_local_checks_preserve_commands_and_reject_empty_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, artifact, draft, revision = (str(uuid4()) for _ in range(5))
    calls: list[tuple[Any, ...]] = []

    class Store:
        def create_revision(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            command = args[-1]
            return {
                "operationId": command["clientOperationId"],
                "resourceId": revision,
                "committedRevision": 9,
                "state": "committed",
            }

        def run_local_checks(self, *args: Any) -> dict[str, Any]:
            result = self.create_revision(*args)
            result["state"] = "accepted"
            return result

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    headers = {"X-Window-Id": "1", "X-Project-Session": session}
    base = f"/api/v1/projects/{project}"
    command = {
        "clientOperationId": str(uuid4()),
        "expectedRevision": 8,
        "payload": {"draftId": draft},
    }
    async with client(create_app(context)) as http:
        created = await http.post(
            base + f"/artifacts/{artifact}/revisions", headers=headers, json=command
        )
        assert created.status_code == 201, created.text
        assert calls == [(project, session, 1, artifact, command)]
        check = {
            **command,
            "clientOperationId": str(uuid4()),
            "payload": {"revisionIds": [revision], "ruleIds": ["structural", "references"]},
        }
        checked = await http.post(base + "/local-checks", headers=headers, json=check)
        assert checked.status_code == 202, checked.text
        assert calls[-1] == (project, session, 1, check)
        for field in ("revisionIds", "ruleIds"):
            rejected = await http.post(
                base + "/local-checks",
                headers=headers,
                json={**check, "payload": {**check["payload"], field: []}},
            )
            assert rejected.status_code == 422, rejected.text
        assert len(calls) == 2


@pytest.mark.anyio
async def test_revision_pagination_is_finite_and_artifact_state_rejects_private_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path
    project, session, artifact, cursor = (str(uuid4()) for _ in range(4))
    leak = False

    class Store:
        def list_revisions(self, *args: Any, limit: int, cursor: str | None) -> dict[str, Any]:
            assert args == (project, session, 1, artifact)
            assert limit == 1 and cursor is not None
            return {"items": [], "nextCursor": None}

        def get_artifact(self, *args: Any) -> dict[str, Any]:
            assert args == (project, session, 1, artifact)
            result = {
                "id": artifact,
                "kind": "story",
                "adoptedRevisionId": None,
                "confirmedRevisionId": None,
                "needsUpdate": False,
                "latestAdoptionId": None,
            }
            if leak:
                result["path"] = "PRIVATE-VERSION-PATH-SENTINEL"
            return result

    monkeypatch.setattr(ProjectStore, "get", lambda _: Store())
    headers = {"X-Window-Id": "1", "X-Project-Session": session}
    path = f"/api/v1/projects/{project}/artifacts/{artifact}"
    async with client(create_app(context)) as http:
        listed = await http.get(path + f"/revisions?limit=1&cursor={cursor}", headers=headers)
        assert listed.status_code == 200, listed.text
        for query in (
            "limit=201",
            "cursor=no",
            "limit=1&limit=2",
            "offset=1",
            "offset=",
            "limit=1&offset=",
            "limit=",
        ):
            rejected = await http.get(path + "/revisions?" + query, headers=headers)
            assert rejected.status_code == 422
        state = await http.get(path, headers=headers)
        assert state.status_code == 200, state.text
        assert state.json()["data"]["confirmedRevisionId"] is None
        leak = True
        failed = await http.get(path, headers=headers)
        assert failed.status_code == 500, failed.text
        assert "PRIVATE-VERSION-PATH-SENTINEL" not in failed.text


@pytest.mark.anyio
async def test_real_version_lifecycle_keeps_drafts_candidates_confirmation_and_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context()
    context.app_data_dir = tmp_path / "app"
    service = ProjectService(context.app_data_dir)
    monkeypatch.setattr(ProjectStore, "get", lambda _: service)
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(project_command(grant(service, directory, "createProject")), 1)
    session = open_session(service, directory)
    pid, sid = session["projectId"], session["projectSessionId"]
    headers = {"X-Window-Id": "1", "X-Project-Session": sid}
    base = f"/api/v1/projects/{pid}"
    draft = draft_request({"sourceText": "", "brief": ""})
    artifact = draft["payload"]["artifactId"]
    path = base + f"/artifacts/{artifact}"
    revision = 1

    async with client(create_app(context)) as http:

        async def write(suffix: str, payload: dict[str, Any], status: int = 200) -> dict[str, Any]:
            nonlocal revision
            body = {
                "clientOperationId": str(uuid4()),
                "expectedRevision": revision,
                "payload": payload,
            }
            response = await http.post(base + suffix, headers=headers, json=body)
            assert response.status_code == status, response.text
            data: dict[str, Any] = response.json()["data"]
            revision = data["committedRevision"]
            replay = await http.post(base + suffix, headers=headers, json=body)
            assert replay.status_code == status and replay.json()["data"] == data
            return data

        async def save(text: str, brief: str) -> None:
            nonlocal revision
            draft["clientOperationId"] = str(uuid4())
            draft["expectedRevision"] = revision
            draft["payload"]["content"]["content"] = {
                "sourceText": text,
                "brief": brief,
                "inputType": "idea",
            }
            response = await http.put(
                base + f"/drafts/{draft['payload']['draftId']}", headers=headers, json=draft
            )
            assert response.status_code == 200, response.text
            revision = response.json()["data"]["committedRevision"]

        async def adopt(target: str) -> dict[str, Any]:
            preview = await http.post(
                path + "/adoption-preview",
                headers=headers,
                json={"toRevisionId": target, "expectedRevision": revision},
            )
            assert preview.status_code == 200, preview.text
            return await write(
                f"/artifacts/{artifact}/adoptions",
                {
                    "previewId": preview.json()["data"]["previewId"],
                    "toRevisionId": target,
                    "confirm": False,
                },
            )

        await save("", "")
        rejected = await http.post(
            path + "/revisions",
            headers=headers,
            json={
                "clientOperationId": str(uuid4()),
                "expectedRevision": revision,
                "payload": {"draftId": draft["payload"]["draftId"]},
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "INPUT_INCOMPLETE"
        retained = await http.get(base + f"/drafts/{draft['payload']['draftId']}", headers=headers)
        assert retained.json()["data"]["content"]["content"]["sourceText"] == ""
        await save("Original story", "A complete proposal brief")
        first = (
            await write(
                f"/artifacts/{artifact}/revisions", {"draftId": draft["payload"]["draftId"]}, 201
            )
        )["resourceId"]
        state = await http.get(path, headers=headers)
        assert state.json()["data"]["adoptedRevisionId"] is None
        await adopt(first)
        checked = await write(
            "/local-checks", {"revisionIds": [first], "ruleIds": ["structural", "references"]}, 202
        )
        job = await http.get(base + f"/jobs/{checked['resourceId']}", headers=headers)
        assert job.status_code == 200, job.text
        assert job.json()["data"]["state"] == "succeeded"
        check_id = job.json()["data"]["resultId"]
        report = await http.get(base + f"/check-reports/{check_id}", headers=headers)
        assert report.status_code == 200, report.text
        assert report.json()["data"]["outcome"] == "pass"
        assert report.json()["data"]["method"] == "local"
        await write(
            f"/artifacts/{artifact}/confirmations", {"revisionId": first, "checkIds": [check_id]}
        )
        # An actual expense remains unchanged by adoption and undo.
        expense = str(uuid4())
        body = {
            "clientOperationId": str(uuid4()),
            "expectedRevision": revision,
            "payload": {
                "expenseId": expense,
                "category": "procurement",
                "state": "settled",
                "amountMicroCny": 12345,
                "basis": "Local fixture expense",
            },
        }
        recorded = await http.put(
            base + f"/external-expenses/{expense}", headers=headers, json=body
        )
        assert recorded.status_code == 200, recorded.text
        revision = recorded.json()["data"]["committedRevision"]
        before_cost = (await http.get(base + "/cost-summary", headers=headers)).json()["data"]
        await save("Modified story", "A complete proposal brief")
        second = (
            await write(
                f"/artifacts/{artifact}/revisions", {"draftId": draft["payload"]["draftId"]}, 201
            )
        )["resourceId"]
        adopted = await adopt(second)
        state = (await http.get(path, headers=headers)).json()["data"]
        assert state["adoptedRevisionId"] == second and state["confirmedRevisionId"] == first
        await write(
            f"/adoptions/{adopted['resourceId']}/undo", {"adoptionId": adopted["resourceId"]}
        )
        restored = (await http.get(path, headers=headers)).json()["data"]
        assert restored["adoptedRevisionId"] == restored["confirmedRevisionId"] == first
        candidates = await http.get(path + "/revisions", headers=headers)
        assert candidates.status_code == 200, candidates.text
        assert {r["id"] for r in candidates.json()["data"]["items"]} == {first, second}
        after_cost = (await http.get(base + "/cost-summary", headers=headers)).json()["data"]
        assert before_cost == after_cost and after_cost["settledMicroCny"] == 12345
    service.close()
