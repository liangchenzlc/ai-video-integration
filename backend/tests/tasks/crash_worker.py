"""Separate process fixture: durable counter followed by abrupt process exit."""

import os
import sys
import time
from pathlib import Path

from app.services.projects import ProjectService
from app.services.task_adapter import SyntheticAdapter
from tests.storage.test_drafts import open_session
from tests.storage.test_projects import command, grant
from tests.storage.test_task_plans import budget, plan
from tests.tasks.test_executor import start, wait_task

root, mode = Path(sys.argv[1]), sys.argv[2]
directory = root / "project"
directory.mkdir()
service = ProjectService(root / "app")
service.create_project(command(grant(service, directory, "createProject")), 1)
session = open_session(service, directory)


class CrashAdapter(SyntheticAdapter):
    def submit(self, request, token):
        with (root / "submits").open("a") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if mode == "lost":
            os._exit(41)
        if mode == "remote":
            return {"remoteTaskId": "synthetic-known-id"}
        return super().submit(request, token)

    def download(self, result):
        if mode == "download":
            os._exit(42)
        return result


service._tasks.adapter = CrashAdapter()
budget(service, session)
frozen, _ = plan(service, session)
if mode == "prepared":
    service._tasks.executor.enqueue = lambda *args: os._exit(43)
receipt, _ = start(service, session, frozen)
wait_task(service, session, receipt["resourceId"])
if mode == "remote":
    os._exit(44)
time.sleep(10)
os._exit(99)
