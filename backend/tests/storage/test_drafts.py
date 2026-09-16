import copy
import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage.errors import ProjectError
from tests.storage.test_projects import command, grant

Json = dict[str, Any]


@pytest.fixture
def opened(tmp_path: Path) -> Iterator[tuple[ProjectService, Path, Json]]:
    directory = tmp_path / "project"
    directory.mkdir()
    service = ProjectService(tmp_path / "app")
    service.create_project(command(grant(service, directory, "createProject")), 1)
    session = open_session(service, directory)
    yield service, directory, session
    service.close()


def open_session(service: ProjectService, directory: Path, window: int = 1) -> Json:
    return service.open_project(
        {
            "directoryGrantId": grant(service, directory, "openProject", window),
            "requestedMode": "write",
        },
        window,
    )


def request(content: Json, kind: str = "story", revision: int = 1) -> Json:
    return {
        "clientOperationId": str(uuid4()),
        "expectedRevision": revision,
        "payload": {
            "draftId": str(uuid4()),
            "artifactId": str(uuid4()),
            "baseRevisionId": None,
            "content": {"kind": kind, "content": content},
        },
    }


def save(service: ProjectService, session: Json, body: Json) -> Json:
    return service.save_draft(
        session["projectId"], session["projectSessionId"], 1, body["payload"]["draftId"], body
    )


def read(service: ProjectService, session: Json, body: Json) -> Json:
    return service.get_draft(
        session["projectId"], session["projectSessionId"], 1, body["payload"]["draftId"]
    )


@pytest.mark.parametrize(
    "kind,content",
    [
        ("story", {}),
        ("story", {"sourceText": "", "brief": ""}),
        ("story", {"scenes": [{}], "requirements": [{"text": ""}]}),
        ("asset", {}),
        ("shot", {"events": [{}], "references": [{"crop": {}}]}),
        ("speech", {}),
        ("subtitle", {"cues": [{"time": {}}]}),
        ("timeline", {"clips": [{"keyframes": [{}]}]}),
        ("observation", {}),
    ],
)
def test_incomplete_draft_round_trips_after_reopen(
    opened: tuple[ProjectService, Path, Json],
    kind: str,
    content: Json,
) -> None:
    service, directory, session = opened
    body = request(content, kind)
    receipt = save(service, session, body)
    assert receipt == {
        "operationId": body["clientOperationId"],
        "resourceId": body["payload"]["draftId"],
        "committedRevision": 2,
        "state": "committed",
    }
    service.close()
    restarted = ProjectService(service.app_data_dir)
    try:
        session = open_session(restarted, directory)
        draft = read(restarted, session, body)
        expected = copy.deepcopy(body["payload"]["content"])
        if "sourceText" in content:
            expected["content"]["sourceHash"] = hashlib.sha256(
                content["sourceText"].encode("utf-8")
            ).hexdigest()
        assert draft == {
            "id": body["payload"]["draftId"],
            "artifactId": body["payload"]["artifactId"],
            "baseRevisionId": None,
            "content": expected,
        }
        assert restarted.get_project_operation(
            session["projectId"], session["projectSessionId"], 1, body["clientOperationId"]
        ) == {"operationId": body["clientOperationId"], "state": "committed", "receipt": receipt}
    finally:
        restarted.close()


def test_source_text_exact_hash_and_same_length_edits(
    opened: tuple[ProjectService, Path, Json],
) -> None:
    service, _, session = opened
    body = request({"sourceText": "甲\r\n😀\n乙"})
    untouched = copy.deepcopy(body)
    save(service, session, body)
    assert body == untouched
    first = read(service, session, body)["content"]["content"]
    assert first["sourceText"] == "甲\r\n😀\n乙"
    assert first["sourceHash"] == hashlib.sha256("甲\r\n😀\n乙".encode()).hexdigest()
    body["clientOperationId"] = str(uuid4())
    body["expectedRevision"] = 2
    body["payload"]["content"]["content"]["sourceText"] = "丙\r\n😀\n乙"
    save(service, session, body)
    second = read(service, session, body)["content"]["content"]
    assert second["sourceHash"] != first["sourceHash"]
    assert second["sourceHash"] != hashlib.sha256("丙\n😀\n乙".encode()).hexdigest()


def test_replay_precedes_cas_and_different_request_reuse_rejected(
    opened: tuple[ProjectService, Path, Json],
) -> None:
    service, _, session = opened
    body = request({"sourceText": "saved"})
    receipt = save(service, session, body)
    project = service.get_project(session["projectId"], session["projectSessionId"], 1)
    assert save(service, session, body) == receipt
    assert service.get_project(session["projectId"], session["projectSessionId"], 1) == project
    changed = copy.deepcopy(body)
    changed["payload"]["content"]["content"]["sourceText"] = "other"
    with pytest.raises(ProjectError, match="OPERATION_ID_REUSED"):
        save(service, session, changed)
    changed["clientOperationId"] = str(uuid4())
    with pytest.raises(ProjectError, match="REVISION_CONFLICT"):
        save(service, session, changed)
    assert read(service, session, body)["content"]["content"]["sourceText"] == "saved"


@pytest.mark.parametrize(
    "content",
    [
        {"sourceText": "text", "sourceHash": "0" * 64},
        {"sourceText": 1},
        {"entryType": "invalid"},
        {"sourceText": "😀" * 100001},
        {"requirements": [{"id": "bad"}]},
        {"scenes": [{"extra": "bad"}]},
        {"sourceHash": "invalid"},
    ],
)
def test_invalid_content_leaves_no_commit(
    opened: tuple[ProjectService, Path, Json], content: Json
) -> None:
    service, _, session = opened
    body = request(content)
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        save(service, session, body)
    assert (
        service.get_project(session["projectId"], session["projectSessionId"], 1)["revision"] == 1
    )
    assert service.list_drafts(session["projectId"], session["projectSessionId"], 1) == []


@pytest.mark.parametrize("change", ["artifactId", "baseRevisionId", "kind", "draftId"])
def test_existing_draft_identity_cannot_change(
    opened: tuple[ProjectService, Path, Json], change: str
) -> None:
    service, _, session = opened
    body = request({})
    save(service, session, body)
    draft_id = body["payload"]["draftId"]
    body["clientOperationId"] = str(uuid4())
    body["expectedRevision"] = 2
    if change == "kind":
        body["payload"]["content"]["kind"] = "asset"
    else:
        body["payload"][change] = str(uuid4())
    with pytest.raises(ProjectError):
        service.save_draft(session["projectId"], session["projectSessionId"], 1, draft_id, body)
    assert (
        service.get_project(session["projectId"], session["projectSessionId"], 1)["revision"] == 2
    )


def test_initial_base_revision_is_not_accepted(opened: tuple[ProjectService, Path, Json]) -> None:
    service, _, session = opened
    body = request({})
    body["payload"]["baseRevisionId"] = str(uuid4())
    with pytest.raises(ProjectError):
        save(service, session, body)


def test_reader_can_query_but_cannot_write_or_replay(
    opened: tuple[ProjectService, Path, Json],
) -> None:
    service, directory, session = opened
    body = request({})
    save(service, session, body)
    reader = open_session(service, directory, 2)
    args = (reader["projectId"], reader["projectSessionId"], 2)
    assert service.get_draft(*args, body["payload"]["draftId"])
    assert service.list_drafts(*args)
    assert service.get_project_operation(*args, body["clientOperationId"])["state"] == "committed"
    with pytest.raises(ProjectError, match="PROJECT_READ_ONLY"):
        service.save_draft(*args, body["payload"]["draftId"], body)


@pytest.mark.parametrize(
    "method", ["save_draft", "get_draft", "list_drafts", "get_project_operation"]
)
def test_identity_checked_before_data_access(
    opened: tuple[ProjectService, Path, Json], method: str
) -> None:
    service, _, session = opened
    body = request({})
    save(service, session, body)
    suffix: tuple[Any, ...] = ()
    if method in {"save_draft", "get_draft"}:
        suffix = (body["payload"]["draftId"],)
    if method == "save_draft":
        suffix += (body,)
    if method == "get_project_operation":
        suffix = (body["clientOperationId"],)
    action = getattr(service, method)
    with pytest.raises(ProjectError, match="SESSION_EXPIRED"):
        action(session["projectId"], session["projectSessionId"], 2, *suffix)
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        action(str(uuid4()), session["projectSessionId"], 1, *suffix)


def test_transaction_abort_preserves_draft_revision_and_receipt(
    opened: tuple[ProjectService, Path, Json],
) -> None:
    service, directory, session = opened
    body = request({"sourceText": "original"})
    save(service, session, body)
    original = read(service, session, body)
    project = service.get_project(session["projectId"], session["projectSessionId"], 1)
    # A database-side failure after draft/project writes must roll back the whole transaction.
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute(
            "CREATE TRIGGER abort_receipt BEFORE INSERT ON operations "
            "BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END"
        )
    body["expectedRevision"] = 2
    body["clientOperationId"] = str(uuid4())
    body["payload"]["content"]["content"]["sourceText"] = "replacement"
    with pytest.raises(ProjectError, match="STORAGE_UNAVAILABLE"):
        save(service, session, body)
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute("DROP TRIGGER abort_receipt")
    assert read(service, session, body) == original
    assert service.get_project(session["projectId"], session["projectSessionId"], 1) == project
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        service.get_project_operation(
            session["projectId"], session["projectSessionId"], 1, body["clientOperationId"]
        )


def test_list_is_bounded_summary_with_committed_time(
    opened: tuple[ProjectService, Path, Json],
) -> None:
    service, directory, session = opened
    latest: Json = {}
    for revision in range(1, 52):
        latest = request({"sourceText": "正文"}, revision=revision)
        save(service, session, latest)
    rows = service.list_drafts(session["projectId"], session["projectSessionId"], 1)
    assert len(rows) == 50
    assert rows[0]["id"] == latest["payload"]["draftId"]
    assert set(rows[0]) == {"id", "artifactId", "kind", "savedAt"}
    assert (
        rows[0]["savedAt"]
        == service.get_project(session["projectId"], session["projectSessionId"], 1)["savedAt"]
    )
    with sqlite3.connect(directory / "project.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 52
        assert db.execute("SELECT event_sequence FROM projects").fetchone()[0] == 0
        for table in ("media_files", "import_intents", "local_jobs"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
