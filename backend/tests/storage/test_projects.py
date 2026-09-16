import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def run_child(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(args, cwd=BACKEND_ROOT, **kwargs)


def service_class() -> Any:
    from app.services.projects import ProjectService

    return ProjectService


def grant(service: Any, directory: Path, purpose: str, window: int = 1) -> str:
    identifier = str(uuid4())
    service.register_grant(
        {
            "clientOperationId": str(uuid4()),
            "expectedRevision": 0,
            "payload": {
                "grantId": identifier,
                "path": str(directory),
                "purpose": purpose,
                "windowId": window,
            },
        },
        window,
    )
    return identifier


def command(identifier: str) -> dict[str, Any]:
    return {
        "clientOperationId": str(uuid4()),
        "expectedRevision": 0,
        "payload": {
            "directoryGrantId": identifier,
            "name": "A project",
            "aspect": "16:9",
            "resolution": "1080p",
            "fps": {"numerator": 24, "denominator": 1},
            "targetMs": 60000,
        },
    }


@pytest.fixture
def project(tmp_path: Path) -> Any:
    directory = tmp_path / "project"
    directory.mkdir()
    service = service_class()(tmp_path / "app")
    yield service, directory
    service.close()


def test_create_replay_and_operation_conflict(project: Any) -> None:
    service, directory = project
    request = command(grant(service, directory, "createProject"))
    first = service.create_project(request, 1)
    assert service.create_project(request, 1) == first
    assert service.get_global_operation(request["clientOperationId"])["receipt"] == first
    request["payload"]["name"] = "Changed"
    with pytest.raises(Exception, match="OPERATION_ID_REUSED"):
        service.create_project(request, 1)


def test_open_lock_close_ownership_and_recent(project: Any) -> None:
    service, directory = project
    receipt = service.create_project(command(grant(service, directory, "createProject")), 1)
    first = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    second = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject", 2), "requestedMode": "write"},
        2,
    )
    assert first["mode"] == "write"
    assert second["mode"] == "read"
    assert first["projectId"] == receipt["resourceId"]
    with pytest.raises(Exception, match="SESSION_EXPIRED"):
        service.get_project(first["projectId"], first["projectSessionId"], 2)
    service.close_session(first["projectSessionId"], 1)
    third = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    assert third["mode"] == "write"
    assert str(directory) not in json.dumps(service.recent_projects())


def test_corrupt_and_nonempty_directories_preserved(project: Any) -> None:
    service, directory = project
    source = directory / "source.txt"
    source.write_bytes(b"unique original")
    with pytest.raises(Exception, match="DIRECTORY_NOT_EMPTY"):
        service.create_project(command(grant(service, directory, "createProject")), 1)
    assert source.read_bytes() == b"unique original"
    database = directory / "project.sqlite3"
    database.write_bytes(b"broken database original")
    with pytest.raises(Exception, match="PROJECT_CORRUPT"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    assert database.read_bytes() == b"broken database original"


def test_exact_current_tables_and_connection_pragmas(project: Any) -> None:
    from app.storage.database import connect

    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    with connect(directory / "project.sqlite3", "ro") as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {
            "projects",
            "operations",
            "drafts",
            "media_files",
            "import_intents",
            "local_jobs",
            "stage_models",
            "stage_budgets",
            "task_plans",
            "planned_steps",
            "user_tasks",
            "service_calls",
            "call_events",
            "cost_entries",
            "external_expenses",
            "uploads",
            "artifacts",
            "revisions",
            "revision_media",
            "dependencies",
            "task_inputs",
            "adoptions",
            "check_runs",
            "checks",
            "task_plan_inputs",
        }
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 3000
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5


def test_missing_database_not_created(project: Any) -> None:
    service, directory = project
    with pytest.raises(Exception, match="PROJECT_NOT_FOUND"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    assert list(directory.iterdir()) == []


def test_recovery_after_publish_retains_original_receipt(project: Any) -> None:
    service, directory = project
    request = command(grant(service, directory, "createProject"))
    receipt = service.create_project(request, 1)
    service.close()
    with sqlite3.connect(service.app_data_dir / "application.sqlite3") as db:
        db.execute("UPDATE global_operations SET state='prepared', receipt_json=NULL")
    restarted = service_class()(service.app_data_dir)
    try:
        assert restarted.create_project(request, 1) == receipt
    finally:
        restarted.close()


def test_grant_purpose_window_single_use_and_expiry(project: Any, monkeypatch: Any) -> None:
    service, directory = project
    identifier = grant(service, directory, "createProject")
    request = command(identifier)
    with pytest.raises(Exception, match="GRANT_REJECTED"):
        service.create_project(request, 2)
    with pytest.raises(Exception, match="GRANT_REJECTED"):
        service.open_project({"directoryGrantId": identifier, "requestedMode": "read"}, 1)
    service.create_project(request, 1)
    with pytest.raises(Exception, match="GRANT_REJECTED"):
        service.create_project(command(identifier), 1)
    expired = grant(service, directory, "openProject")
    monkeypatch.setattr("app.services.projects.time.monotonic", lambda: float("inf"))
    with pytest.raises(Exception, match="GRANT_REJECTED"):
        service.open_project({"directoryGrantId": expired, "requestedMode": "read"}, 1)


def test_consumed_grant_cannot_be_registered_again(project: Any) -> None:
    service, directory = project
    identifier = grant(service, directory, "createProject")
    service.create_project(command(identifier), 1)
    with pytest.raises(Exception, match="GRANT_REJECTED"):
        service.register_grant(
            {
                "clientOperationId": str(uuid4()),
                "expectedRevision": 0,
                "payload": {
                    "grantId": identifier,
                    "path": str(directory),
                    "purpose": "openProject",
                    "windowId": 1,
                },
            },
            1,
        )


def test_write_lock_crosses_process_boundary(project: Any) -> None:
    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    script = """
import sys
from pathlib import Path
from app.storage.locking import ProjectLock
lock = ProjectLock.acquire(Path(sys.argv[1]))
print('locked' if lock is None else 'acquired')
if lock: lock.close()
"""
    result = run_child(
        [sys.executable, "-c", script, str(directory)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip() == "locked"
    service.close_session(session["projectSessionId"], 1)
    result = run_child(
        [sys.executable, "-c", script, str(directory)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip() == "acquired"


@pytest.mark.parametrize("boundary", ["before_publish", "after_publish"])
def test_process_exit_creation_recovery(tmp_path: Path, boundary: str) -> None:
    directory = tmp_path / "project"
    directory.mkdir()
    script = """
import json, os, sys
from pathlib import Path
from uuid import uuid4
from app.services.projects import ProjectService
service = ProjectService(Path(sys.argv[1]))
grant_id = str(uuid4())
service.register_grant({'clientOperationId':str(uuid4()),'expectedRevision':0,
 'payload':{'grantId':grant_id,'path':sys.argv[2],'purpose':'createProject','windowId':1}},1)
request = {'clientOperationId':str(uuid4()),'expectedRevision':0,'payload':{
 'directoryGrantId':grant_id,'name':'Crash project','aspect':'16:9','resolution':'720p',
 'fps':{'numerator':30,'denominator':1},'targetMs':12345}}
Path(sys.argv[3]).write_text(json.dumps(request))
rename = Path.rename
def crash_rename(self, target):
 if sys.argv[4] == 'before_publish': os._exit(71)
 result = rename(self, target)
 os._exit(72)
Path.rename = crash_rename
service.create_project(request,1)
"""
    if os.name != "nt":
        pytest.skip("Windows atomic publish boundary")
    request_file = tmp_path / "request.json"
    result = run_child(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "app"),
            str(directory),
            str(request_file),
            boundary,
        ],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == (71 if boundary == "before_publish" else 72), result.stderr
    request = json.loads(request_file.read_text())
    restarted = service_class()(tmp_path / "app")
    try:
        receipt = restarted.create_project(request, 1)
        assert (
            receipt["resourceId"]
            == json.loads((directory / ".ai-video-project.json").read_text())["projectId"]
        )
        session = restarted.open_project(
            {
                "directoryGrantId": grant(restarted, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
        assert session["project"]["targetMs"] == 12345
    finally:
        restarted.close()


def test_unknown_recovery_marker_preserved(project: Any) -> None:
    service, directory = project
    request = command(grant(service, directory, "createProject"))
    service.create_project(request, 1)
    service.close()
    marker = directory / ".ai-video-project.json"
    marker.write_bytes(b'{"unknown":"original"}')
    with sqlite3.connect(service.app_data_dir / "application.sqlite3") as db:
        db.execute("UPDATE global_operations SET state='prepared',receipt_json=NULL")
    original = (directory / "project.sqlite3").read_bytes()
    restarted = service_class()(service.app_data_dir)
    try:
        with pytest.raises(Exception, match="PROJECT_RECOVERY_REQUIRED"):
            restarted.get_global_operation(request["clientOperationId"])
        assert marker.read_bytes() == b'{"unknown":"original"}'
        assert (directory / "project.sqlite3").read_bytes() == original
    finally:
        restarted.close()


def test_recovery_checkpoints_committed_wal_before_publish(project: Any) -> None:
    service, directory = project
    request = command(grant(service, directory, "createProject"))
    service.create_project(request, 1)
    service.close()
    staging = directory / (".ai-video-staging-" + request["clientOperationId"])
    (directory / "project.sqlite3").rename(staging / "project.sqlite3")
    # Move the complete SQLite family to reproduce a pre-publication staging crash.
    for suffix in ("-wal", "-shm"):
        sidecar = directory / ("project.sqlite3" + suffix)
        if sidecar.exists():
            sidecar.rename(staging / sidecar.name)
    script = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("PRAGMA wal_autocheckpoint=0")
db.execute("UPDATE projects SET saved_at='2030-01-01T00:00:00+00:00'")
db.commit()
os._exit(0)
"""
    run_child(
        [sys.executable, "-c", script, str(staging / "project.sqlite3")], check=True, timeout=20
    )
    assert (staging / "project.sqlite3-wal").stat().st_size > 0
    with sqlite3.connect(service.app_data_dir / "application.sqlite3") as db:
        db.execute("UPDATE global_operations SET state='prepared',receipt_json=NULL")
    restarted = service_class()(service.app_data_dir)
    try:
        restarted.get_global_operation(request["clientOperationId"])
        session = restarted.open_project(
            {
                "directoryGrantId": grant(restarted, directory, "openProject"),
                "requestedMode": "read",
            },
            1,
        )
        assert session["project"]["savedAt"] == "2030-01-01T00:00:00+00:00"
    finally:
        restarted.close()


def test_read_only_does_not_migrate_existing_database(project: Any) -> None:
    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    database = directory / "project.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA user_version=1")
    original = database.read_bytes()
    with pytest.raises(Exception, match="PROJECT_VERSION_UNSUPPORTED"):
        service.open_project(
            {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "read"},
            1,
        )
    assert database.read_bytes() == original


def test_incomplete_schema_is_not_opened_or_repaired(project: Any) -> None:
    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    database = directory / "project.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("DROP TABLE operations")
    original = database.read_bytes()
    with pytest.raises(Exception, match="PROJECT_CORRUPT"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    assert database.read_bytes() == original


def test_corrupt_columns_return_fixed_error(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute("ALTER TABLE projects RENAME COLUMN fps_n TO invalid_column")
    with pytest.raises(ProjectError, match="PROJECT_CORRUPT"):
        service.open_project(
            {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "read"},
            1,
        )


def test_project_id_replacement_cannot_cross_session(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "read"}, 1
    )
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute("UPDATE projects SET id=?", (str(uuid4()),))
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        service.get_project(session["projectId"], session["projectSessionId"], 1)


def test_reset_revokes_sessions_grants_and_releases_locks(project: Any) -> None:
    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    identifier = grant(service, directory, "openProject")
    service.reset()
    with pytest.raises(Exception, match="SESSION_EXPIRED"):
        service.get_project(session["projectId"], session["projectSessionId"], 1)
    with pytest.raises(Exception, match="GRANT_REJECTED"):
        service.open_project({"directoryGrantId": identifier, "requestedMode": "write"}, 1)
    reopened = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    assert reopened["mode"] == "write"


def test_same_window_reopen_reuses_live_session(project: Any) -> None:
    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    first = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    retry = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    assert retry == first
    other = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject", 2), "requestedMode": "write"},
        2,
    )
    assert other["mode"] == "read"
    assert other["projectSessionId"] != first["projectSessionId"]
    service.close_session(first["projectSessionId"], 1)
    fresh = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    assert fresh["mode"] == "write"
    assert fresh["projectSessionId"] != first["projectSessionId"]


def test_close_session_retry_is_idempotent_but_owner_checked(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    with pytest.raises(ProjectError, match="SESSION_EXPIRED"):
        service.close_session(session["projectSessionId"], 2)
    assert service.get_project(session["projectId"], session["projectSessionId"], 1)
    assert service.close_session(session["projectSessionId"], 1) is None
    assert service.close_session(session["projectSessionId"], 1) is None


def test_explicit_read_never_reuses_same_window_writer(project: Any) -> None:
    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    writer = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    reader = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "read"}, 1
    )
    assert reader["mode"] == "read"
    assert reader["project"]["readOnly"] is True
    assert reader["projectSessionId"] != writer["projectSessionId"]
    retry = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "read"}, 1
    )
    assert retry == reader
    assert (
        service.get_project(writer["projectId"], writer["projectSessionId"], 1)["readOnly"] is False
    )
    # Main opens the replacement first, then closes its old writer.
    service.close_session(writer["projectSessionId"], 1)
    assert (
        service.get_project(reader["projectId"], reader["projectSessionId"], 1)["readOnly"] is True
    )
    other = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject", 2), "requestedMode": "write"},
        2,
    )
    assert other["mode"] == "write"


def test_stale_recent_cannot_resolve_a_replacement_project(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    receipt = service.create_project(command(grant(service, directory, "createProject")), 1)
    assert service.recent_project_directory(receipt["resourceId"]) == directory
    with sqlite3.connect(directory / "project.sqlite3") as db:
        db.execute("UPDATE projects SET id=?", (str(uuid4()),))
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        service.recent_project_directory(receipt["resourceId"])


def test_pending_creation_without_marker_preserves_files(project: Any) -> None:
    service, directory = project
    request = command(grant(service, directory, "createProject"))
    service.create_project(request, 1)
    service.close()
    (directory / ".ai-video-project.json").unlink()
    with sqlite3.connect(service.app_data_dir / "application.sqlite3") as db:
        db.execute("UPDATE global_operations SET state='prepared',receipt_json=NULL")
    original = (directory / "project.sqlite3").read_bytes()
    restarted = service_class()(service.app_data_dir)
    try:
        with pytest.raises(Exception, match="PROJECT_RECOVERY_REQUIRED"):
            restarted.create_project(request, 1)
        assert (directory / "project.sqlite3").read_bytes() == original
        assert not (directory / ".ai-video-project.json").exists()
    finally:
        restarted.close()


def test_invalid_operation_uuid_has_fixed_validation_error(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    with pytest.raises(ProjectError) as error:
        service.get_global_operation(str(directory))
    assert error.value.code == "VALIDATION_FAILED"
    assert error.value.status_code == 422
    assert str(directory) not in str(error.value)


@pytest.mark.parametrize("sidecar", ["-wal", "-shm"])
@pytest.mark.parametrize("published", [False, True])
def test_unknown_recovery_sidecar_preserved(project: Any, sidecar: str, published: bool) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    request = command(grant(service, directory, "createProject"))
    service.create_project(request, 1)
    service.close()
    database = directory / "project.sqlite3"
    if not published:
        staging = directory / (".ai-video-staging-" + request["clientOperationId"])
        database = database.rename(staging / "project.sqlite3")
    residue = Path(str(database) + sidecar)
    residue.write_bytes(b"Unknown original bytes that must not disappear")
    before = {p.name: p.read_bytes() for p in database.parent.iterdir() if p.is_file()}
    with sqlite3.connect(service.app_data_dir / "application.sqlite3") as db:
        db.execute("UPDATE global_operations SET state='prepared',receipt_json=NULL")
    restarted = service_class()(service.app_data_dir)
    try:
        with pytest.raises(ProjectError, match="PROJECT_RECOVERY_REQUIRED"):
            restarted.get_global_operation(request["clientOperationId"])
        assert {p.name: p.read_bytes() for p in database.parent.iterdir() if p.is_file()} == before
        with sqlite3.connect(service.app_data_dir / "application.sqlite3") as db:
            assert db.execute("SELECT state FROM global_operations").fetchone()[0] == "prepared"
    finally:
        restarted.close()


def test_future_project_format_not_opened_for_write(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    database = directory / "project.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("UPDATE projects SET format_version=999")
    before = database.read_bytes()
    with pytest.raises(ProjectError, match="PROJECT_VERSION_UNSUPPORTED"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "table,column",
    [
        ("projects", "saved_at"),
        ("operations", "request_hash"),
        ("drafts", "payload_json"),
        ("media_files", "relative_path"),
        ("import_intents", "operation_id"),
        ("local_jobs", "snapshot_json"),
    ],
)
def test_all_project_table_structures_checked(project: Any, table: str, column: str) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    database = directory / "project.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(f"ALTER TABLE {table} RENAME COLUMN {column} TO invalid_column")
    before = database.read_bytes()
    with pytest.raises(ProjectError, match="PROJECT_CORRUPT"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    assert database.read_bytes() == before


def test_required_unique_job_index_checked(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, directory = project
    service.create_project(command(grant(service, directory, "createProject")), 1)
    database = directory / "project.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("DROP INDEX one_heavy_job")
    before = database.read_bytes()
    with pytest.raises(ProjectError, match="PROJECT_CORRUPT"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    assert database.read_bytes() == before


@pytest.mark.parametrize("damage", ["wal_header", "wal_frame", "wal_tail", "shm_header"])
def test_sqlite_sidecar_checksum_damage_preserved(tmp_path: Path, damage: str) -> None:
    from app.storage.errors import ProjectError
    from app.storage.recovery import validate_recovery_sidecars

    database = tmp_path / "sample.sqlite3"
    script = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA wal_autocheckpoint=0')
db.execute('CREATE TABLE example (value TEXT)')
db.execute("INSERT INTO example VALUES ('original committed content')")
db.commit()
os._exit(0)
"""
    run_child([sys.executable, "-c", script, str(database)], check=True, timeout=20)
    validate_recovery_sidecars(database)
    sidecar = Path(str(database) + ("-shm" if damage == "shm_header" else "-wal"))
    content = bytearray(sidecar.read_bytes())
    if damage == "wal_tail":
        content.extend(b"unknown trailing original")
    else:
        offset = 64 if damage == "wal_frame" else 0
        content[offset] ^= 1
    sidecar.write_bytes(content)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ProjectError, match="PROJECT_RECOVERY_REQUIRED"):
        validate_recovery_sidecars(database)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_unknown_operation_is_not_found(project: Any) -> None:
    from app.storage.errors import ProjectError

    service, _ = project
    with pytest.raises(ProjectError) as error:
        service.get_global_operation(str(uuid4()))
    assert error.value.code == "OBJECT_NOT_FOUND"
    assert error.value.status_code == 404


def test_existing_directory_grant_rechecked_after_junction_swap(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction protection")
    service = service_class()(tmp_path / "app")
    selected = tmp_path / "selected"
    selected.mkdir()
    original = tmp_path / "original"
    original.mkdir()
    identifier = grant(service, selected, "createProject")
    selected.rmdir()
    run_child(
        ["cmd", "/c", "mklink", "/J", str(selected), str(original)],
        check=True,
        capture_output=True,
        timeout=20,
    )
    try:
        with pytest.raises(Exception, match="UNSAFE_PROJECT_PATH"):
            service.create_project(command(identifier), 1)
        assert list(original.iterdir()) == []
    finally:
        service.close()
        selected.rmdir()


def test_real_junction_rejected(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction protection")
    target = tmp_path / "original"
    target.mkdir()
    junction = tmp_path / "junction"
    run_child(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        timeout=20,
    )
    service = service_class()(tmp_path / "app")
    try:
        with pytest.raises(Exception, match="UNSAFE_PROJECT_PATH"):
            grant(service, junction, "createProject")
        assert list(target.iterdir()) == []
    finally:
        service.close()
        junction.rmdir()


@pytest.mark.parametrize("relative", ["../escape", "/root", "C:/file", "a\\b", "a/../b"])
def test_unsafe_relative_paths_rejected(tmp_path: Path, relative: str) -> None:
    from app.storage.paths import relative_file

    with pytest.raises(Exception, match="UNSAFE_PROJECT_PATH"):
        relative_file(tmp_path, relative)
