import time

import pytest
from app.services.task_adapter import SyntheticAdapter
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_task_plans import budget, cmd, invoke, plan


class Counter(SyntheticAdapter):
    def __init__(self, fail=0, lost=False):
        self.submits = 0
        self.queries = 0
        self.downloads = 0
        self.fail = fail
        self.lost = lost

    def submit(self, request, token):
        self.submits += 1
        if self.lost:
            raise TimeoutError("accepted, response lost")
        if self.submits == self.fail:
            return {"failed": True}
        return super().submit(request, token)

    def query(self, remote_task_id, request):
        self.queries += 1
        return super().query(remote_task_id, request)

    def download(self, result):
        self.downloads += 1
        return super().download(result)


def start(service, session, frozen):
    command = cmd(
        service,
        session,
        {
            "planId": frozen["id"],
            "authorizedMaximumMicroCny": frozen["maximumMicroCny"],
            "disclosureAccepted": True,
        },
    )
    receipt = invoke(service, session, "start_task", command)
    return receipt, command


def wait_task(service, session, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = invoke(service, session, "get_task", task_id)
        if task["state"] not in {"pending", "running"}:
            return task
        time.sleep(0.01)
    raise AssertionError(task)


def test_start_replay_keeps_one_submit_and_result(opened):
    service, directory, session = opened
    counter = Counter()
    service._tasks.adapter = counter
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, command = start(service, session, frozen)
    assert invoke(service, session, "start_task", command) == receipt
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "complete"
    assert counter.submits == 1
    assert counter.downloads == 1
    assert len(task["callIds"]) == 1
    with connect(directory / "project.sqlite3", "ro") as db:
        assert "synthetic" in db.execute("SELECT result_json FROM service_calls").fetchone()[0]
    assert invoke(service, session, "get_cost_summary")["reservedMicroCny"] == 100_000


def test_lost_response_never_resubmitted_and_reservation_retained(opened):
    service, directory, session = opened
    counter = Counter(lost=True)
    service._tasks.adapter = counter
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "result_unknown"
    call_id = task["callIds"][0]
    with pytest.raises(ProjectError, match="RECOVERY_NOT_ALLOWED"):
        invoke(
            service, session, "recover_call", call_id, cmd(service, session, {"action": "query"})
        )
    invoke(
        service, session, "recover_call", call_id, cmd(service, session, {"action": "stop_waiting"})
    )
    assert counter.submits == 1
    summary = invoke(service, session, "get_cost_summary")
    assert summary["containsUnknown"] is True
    assert summary["reservedMicroCny"] == 100_000
    assert invoke(service, session, "get_task", task["id"])["observationStopped"] is True


def test_partial_stops_third_candidate_and_excludes_submitted_prediction(opened):
    service, _, session = opened
    counter = Counter(fail=2)
    service._tasks.adapter = counter
    budget(service, session)
    frozen, _ = plan(service, session, candidates=3)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "partial"
    assert counter.submits == 2
    summary = invoke(service, session, "get_cost_summary")
    assert summary["reservedMicroCny"] == 200_000
    assert summary["remainingWorkMicroCny"] == 100_000
    assert summary["forecastMicroCny"] == 300_000


def test_settlement_corrections_are_append_only_and_not_double_counted(opened):
    service, directory, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    call_id = task["callIds"][0]
    body = cmd(
        service,
        session,
        {
            "settledMicroCny": 90_000,
            "basis": "synthetic invoice",
            "evidenceMediaIds": [],
            "reason": "initial",
        },
    )
    first = invoke(service, session, "settle_call", call_id, body)
    assert invoke(service, session, "settle_call", call_id, body) == first
    body = cmd(
        service,
        session,
        {
            "settledMicroCny": 80_000,
            "basis": "corrected synthetic invoice",
            "evidenceMediaIds": [],
            "reason": "correction",
        },
    )
    invoke(service, session, "settle_call", call_id, body)
    summary = invoke(service, session, "get_cost_summary")
    assert (summary["settledMicroCny"], summary["reservedMicroCny"]) == (80_000, 0)
    with connect(directory / "project.sqlite3", "ro") as db:
        assert (
            db.execute("SELECT count(*) FROM call_events WHERE event_type='settlement'").fetchone()[
                0
            ]
            == 2
        )
    with pytest.raises(ProjectError, match="BUDGET_EXCEEDED"):
        budget(service, session, 79_999)


def test_task_authorization_checks_actual_overestimate_before_next_candidate(opened):
    service, directory, session = opened
    counter = Counter()
    service._tasks.adapter = counter
    budget(service, session)
    frozen, _ = plan(service, session, candidates=2)
    from app.storage import costs

    with connect(directory / "project.sqlite3") as db, db:
        from uuid import uuid4

        task_id = str(uuid4())
        db.execute(
            "INSERT INTO user_tasks(id,plan_id,state,active,authorized_maximum_micro_cny) "
            "VALUES(?,?,'pending',0,?)",
            (task_id, frozen["id"], 200_000),
        )
        from app.storage import tasks

        project = service._project_row(db, session["projectId"])
        call_id = tasks.prepare_next(db, project, task_id, counter)
        db.execute(
            "UPDATE cost_entries SET "
            "state='settled',settled_micro_cny=210000,basis='actual bill' WHERE call_id=?",
            (call_id,),
        )
        with pytest.raises(ProjectError, match="BUDGET_EXCEEDED"):
            costs.check_limits(db, project, "story", 0, task_id, 200_000)


def test_replanned_unstarted_work_is_not_predicted_twice(opened):
    service, _, session = opened
    budget(service, session)
    frozen, previous = plan(service, session)
    body = cmd(service, session, previous["payload"])
    invoke(service, session, "plan_task", body)
    assert (
        invoke(service, session, "get_cost_summary")["remainingWorkMicroCny"]
        == frozen["maximumMicroCny"]
    )


def test_external_expenses_preserve_ids_and_separate_estimates(opened):
    from uuid import uuid4

    service, directory, session = opened
    budget(service, session)
    expense = str(uuid4())
    body = cmd(
        service,
        session,
        {
            "expenseId": expense,
            "category": "storage",
            "state": "estimated",
            "amountMicroCny": 300_000,
            "basis": "synthetic forecast",
        },
    )
    invoke(service, session, "set_external_expense", expense, body)
    summary = invoke(service, session, "get_cost_summary")
    assert summary["remainingWorkMicroCny"] == 300_000
    assert summary["reservedMicroCny"] == 0
    body["payload"]["state"] = "pending"
    receipt = invoke(
        service, session, "set_external_expense", expense, cmd(service, session, body["payload"])
    )
    summary = invoke(service, session, "get_cost_summary")
    assert summary["remainingWorkMicroCny"] == 0
    assert summary["reservedMicroCny"] == 300_000
    assert receipt["resourceId"] == expense
    with connect(directory / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0


def test_append_only_event_constraints(opened):
    import sqlite3

    service, directory, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    wait_task(service, session, receipt["resourceId"])
    with connect(directory / "project.sqlite3") as db:
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            db.execute("UPDATE call_events SET event_type='rewritten'")
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            db.execute("DELETE FROM call_events")


def test_cannot_settle_unsubmitted_prepared_call(opened, monkeypatch):
    service, _, session = opened
    budget(service, session)
    frozen, _ = plan(service, session)
    monkeypatch.setattr(service._tasks.executor, "enqueue", lambda *args: None)
    receipt, _ = start(service, session, frozen)
    call_id = invoke(service, session, "get_task", receipt["resourceId"])["callIds"][0]
    with pytest.raises(ProjectError, match="RECOVERY_NOT_ALLOWED"):
        invoke(
            service,
            session,
            "settle_call",
            call_id,
            cmd(
                service,
                session,
                {
                    "settledMicroCny": 0,
                    "basis": "not submitted",
                    "evidenceMediaIds": [],
                    "reason": "invalid",
                },
            ),
        )
