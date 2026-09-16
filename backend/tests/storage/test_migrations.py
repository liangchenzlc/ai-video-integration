import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage.backup import backup_project_database
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_projects import command, grant


def old_project(directory: Path) -> None:
    with connect(directory / "project.sqlite3") as db, db:
        for table in (
            "checks",
            "check_runs",
            "task_plan_inputs",
            "task_inputs",
            "adoptions",
            "dependencies",
            "revision_media",
            "artifacts",
            "revisions",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("DROP VIEW charged_costs")
        for table in (
            "uploads",
            "cost_entries",
            "call_events",
            "service_calls",
            "user_tasks",
            "planned_steps",
            "task_plans",
            "stage_budgets",
            "external_expenses",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("ALTER TABLE projects DROP COLUMN budget_warning_percent")
        db.execute("ALTER TABLE projects DROP COLUMN execution_mode")
        db.execute("DROP TABLE IF EXISTS stage_models")
        db.execute("PRAGMA user_version=2")


def test_new_project_starts_at_current_schema_without_migration_backup(tmp_path: Path) -> None:
    service = ProjectService(tmp_path / "app")
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
    assert not (directory / "backups").exists()
    service.close()


def test_read_does_not_migrate_write_backup_preserves_v2(tmp_path: Path) -> None:
    service = ProjectService(tmp_path / "app")
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    old_project(directory)

    def open_mode(mode: str) -> dict[str, Any]:
        return service.open_project(
            {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": mode}, 1
        )

    read = open_mode("read")
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    service.close_session(read["projectSessionId"], 1)
    write = open_mode("write")
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("SELECT count(*) FROM stage_models").fetchone()[0] == 0
    backups = list((directory / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with connect(backups[0], "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT id FROM projects").fetchone()[0] == write["projectId"]
    service.close()
    moved = tmp_path / "moved"
    directory.rename(moved)
    reopened = ProjectService(tmp_path / "app")
    session = reopened.open_project(
        {"directoryGrantId": grant(reopened, moved, "openProject"), "requestedMode": "write"}, 1
    )
    assert session["projectId"] == write["projectId"]
    reopened.close()


def test_migration_failure_rolls_back_and_retains_backup(tmp_path: Path, monkeypatch: Any) -> None:
    from app.storage import database

    service = ProjectService(tmp_path / "app")
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    old_project(directory)
    original = database.validate_project_schema

    def fail(db: sqlite3.Connection) -> None:
        if db.execute("PRAGMA user_version").fetchone()[0] == 5:
            raise ProjectError("PROJECT_CORRUPT")
        original(db)

    monkeypatch.setattr(database, "validate_project_schema", fail)
    with pytest.raises(ProjectError, match="PROJECT_MIGRATION_FAILED"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            db.execute("SELECT name FROM sqlite_schema WHERE name='stage_models'").fetchone()
            is None
        )
    assert len(list((directory / "backups").glob("*.sqlite3"))) == 1
    service.close()


def test_migration_rechecks_identity_after_backup(tmp_path: Path, monkeypatch: Any) -> None:
    from app.services import projects

    service = ProjectService(tmp_path / "app")
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    old_project(directory)
    original = backup_project_database
    changed_id = str(uuid4())

    def replace_after_backup(path: Path, project_id: str) -> Path:
        saved = original(path, project_id)
        with connect(path / "project.sqlite3") as db, db:
            db.execute("UPDATE projects SET id=?", (changed_id,))
        return saved

    monkeypatch.setattr(projects, "backup_project_database", replace_after_backup)
    with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
        service.open_project(
            {
                "directoryGrantId": grant(service, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT id FROM projects").fetchone()[0] == changed_id
    service.close()


def test_v3_upgrade_preserves_configuration_and_makes_backup(tmp_path: Path) -> None:
    from app.storage import database

    service = ProjectService(tmp_path / "app")
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    old_project(directory)
    capability_id = str(uuid4())
    with connect(directory / "project.sqlite3") as db, db:
        db.execute((Path(database.__file__).parent / "migration_003.sql").read_text("utf-8"))
        db.execute("PRAGMA user_version=3")
        db.execute(
            "INSERT INTO stage_models VALUES(?,?,?)", ("story_adaptation", capability_id, "v1")
        )
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("SELECT capability_id FROM stage_models").fetchone()[0] == capability_id
    backup = next((directory / "backups").glob("*.sqlite3"))
    with connect(backup, "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    assert (
        service.get_budget(session["projectId"], session["projectSessionId"], 1)["executionMode"]
        is None
    )
    service.close()


def test_v4_upgrade_preserves_task_budget_data_and_backup(tmp_path: Path) -> None:
    service = ProjectService(tmp_path / "app")
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    with connect(directory / "project.sqlite3") as db, db:
        for table in (
            "checks",
            "check_runs",
            "task_plan_inputs",
            "task_inputs",
            "adoptions",
            "dependencies",
            "revision_media",
            "artifacts",
            "revisions",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("UPDATE stage_budgets SET limit_micro_cny=123 WHERE stage='story'")
        db.execute("PRAGMA user_version=4")
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "read"}, 1
    )
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
    assert not (directory / "backups").exists()
    service.close_session(session["projectSessionId"], 1)
    service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert (
            db.execute("SELECT limit_micro_cny FROM stage_budgets WHERE stage='story'").fetchone()[
                0
            ]
            == 123
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    backup = next((directory / "backups").glob("*.sqlite3"))
    with connect(backup, "ro") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert (
            db.execute("SELECT limit_micro_cny FROM stage_budgets WHERE stage='story'").fetchone()[
                0
            ]
            == 123
        )
    service.close()
