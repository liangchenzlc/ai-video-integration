import threading
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_drafts import open_session, request, save
from tests.storage.test_projects import command, grant
from tests.storage.test_task_plans import budget, invoke, plan
from tests.tasks.test_executor import Counter, start, wait_task


class BlockingCounter(Counter):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def submit(self, request, token):
        self.entered.set()
        assert self.release.wait(10)
        return super().submit(request, token)


def test_one_slot_across_projects_draft_io_and_detached_lock(opened, tmp_path):
    service, directory, session = opened
    counter = BlockingCounter()
    service._tasks.adapter = counter
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    assert counter.entered.wait(3)
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    service.create_project(command(grant(service, second_dir, "createProject")), 1)
    second = open_session(service, second_dir)
    budget(service, second)
    other_plan, _ = plan(service, second)
    try:
        with pytest.raises(ProjectError, match="TASK_BUSY"):
            start(service, second, other_plan)
        body = request(
            {"brief": "unrelated"},
            revision=service.get_project(session["projectId"], session["projectSessionId"], 1)[
                "revision"
            ],
        )
        save(service, session, body)
        service.close_session(session["projectSessionId"], 1)
        outsider = ProjectService(tmp_path / "outsider")
        try:
            read = open_session(outsider, directory)
            assert read["mode"] == "read"
            assert service.get_task_activity()[0]["projectId"] == session["projectId"]
        finally:
            outsider.close()
    finally:
        counter.release.set()
    reopened = open_session(service, directory)
    assert wait_task(service, reopened, receipt["resourceId"])["state"] == "complete"


def test_all_task_reads_and_replays_bind_persisted_identity(opened):
    service, directory, session = opened
    budget(service, session)
    frozen, original = plan(service, session)
    with connect(directory / "project.sqlite3") as db, db:
        db.execute("UPDATE projects SET id=?", (str(uuid4()),))
    for method, args in [
        ("get_budget", ()),
        ("get_task_plan", (frozen["id"],)),
        ("plan_task", (original,)),
        ("list_tasks", ()),
        ("get_cost_summary", ()),
        ("list_cost_entries", ()),
    ]:
        with pytest.raises(ProjectError, match="OBJECT_NOT_FOUND"):
            invoke(service, session, method, *args)


def test_closed_unknown_task_remains_in_runtime_activity(opened):
    service, _, session = opened
    service._tasks.adapter = Counter(lost=True)
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    assert wait_task(service, session, receipt["resourceId"])["state"] == "result_unknown"
    service._tasks.executor.thread.join(timeout=3)
    service.close_session(session["projectSessionId"], 1)
    assert service.get_task_activity() == [
        {
            "projectId": session["projectId"],
            "projectName": "A project",
            "taskId": receipt["resourceId"],
            "state": "result_unknown",
        }
    ]
