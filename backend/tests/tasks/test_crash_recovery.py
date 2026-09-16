import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.services.projects import ProjectService
from app.storage.errors import ProjectError
from tests.storage.test_drafts import open_session
from tests.storage.test_task_plans import cmd, invoke
from tests.tasks.test_executor import Counter, wait_task


@pytest.mark.parametrize(
    "mode,code", [("lost", 41), ("download", 42), ("prepared", 43), ("remote", 44)]
)
def test_process_crash_preserves_no_resubmit_boundary(tmp_path, mode, code):
    env = dict(os.environ, PYTHONPATH=str(Path("backend").resolve()))
    child = subprocess.run(
        [sys.executable, "backend/tests/tasks/crash_worker.py", str(tmp_path), mode],
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert child.returncode == code, child.stderr.decode(errors="replace")
    service = ProjectService(tmp_path / "app")
    counter = Counter()
    service._tasks.adapter = counter
    try:
        session = open_session(service, tmp_path / "project")
        summary = invoke(service, session, "list_tasks")["items"][0]
        task = invoke(service, session, "get_task", summary["id"])
        call_id = task["callIds"][0]
        call = invoke(service, session, "get_call", call_id)
        assert counter.submits == 0
        assert invoke(service, session, "get_cost_summary")["reservedMicroCny"] == 100_000
        if mode == "lost":
            assert call["state"] == "result_unknown"
            with pytest.raises(ProjectError, match="RECOVERY_NOT_ALLOWED"):
                invoke(
                    service,
                    session,
                    "recover_call",
                    call_id,
                    cmd(service, session, {"action": "query"}),
                )
        elif mode == "prepared":
            assert call["state"] == "prepared"
            invoke(
                service,
                session,
                "continue_task",
                task["id"],
                cmd(service, session, {"confirmedUnsubmittedOnly": True}),
            )
            assert wait_task(service, session, task["id"])["state"] == "complete"
            assert counter.submits == 1
        else:
            action = "download" if mode == "download" else "query"
            invoke(
                service, session, "recover_call", call_id, cmd(service, session, {"action": action})
            )
            assert wait_task(service, session, task["id"])["state"] == "complete"
            assert counter.submits == 0
            assert counter.queries == (1 if mode == "remote" else 0)
            assert counter.downloads == 1
        if mode != "prepared":
            assert len((tmp_path / "submits").read_text().splitlines()) == 1
    finally:
        service.close()
