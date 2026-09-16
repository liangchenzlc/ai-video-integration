"""CNY integer micro-unit ledger; reservations and settlements are mutually exclusive."""

import sqlite3
from typing import Any

from app.storage.errors import ProjectError
from app.storage.task_plans import STAGES, amount


def charged(db: sqlite3.Connection, *, stage: str | None = None, task_id: str | None = None) -> int:
    sql = (
        "SELECT coalesce(sum(c.amount_micro_cny),0) FROM charged_costs c "
        "JOIN service_calls s ON s.id=c.call_id JOIN user_tasks t ON t.id=s.task_id "
        "JOIN task_plans p ON p.id=t.plan_id WHERE 1=1"
    )
    args = []
    if stage is not None:
        sql += " AND p.stage=?"
        args.append(stage)
    if task_id is not None:
        sql += " AND t.id=?"
        args.append(task_id)
    result = db.execute(sql, args).fetchone()[0]
    if stage is None and task_id is None:
        result += db.execute(
            "SELECT coalesce(sum(amount_micro_cny),0) FROM external_expenses WHERE "
            "state!='estimated'"
        ).fetchone()[0]
    return int(result)


def budget(db: sqlite3.Connection, project: sqlite3.Row) -> dict[str, Any]:
    return {
        "totalMicroCny": project["budget_micro_cny"],
        "allocations": [
            {"stage": row["stage"], "limitMicroCny": row["limit_micro_cny"]}
            for row in db.execute("SELECT * FROM stage_budgets ORDER BY stage")
        ],
        "warningPercent": project["budget_warning_percent"],
        "executionMode": project["execution_mode"],
    }


def set_budget(db: sqlite3.Connection, project: sqlite3.Row, payload: dict[str, Any]) -> None:
    total = amount(payload["totalMicroCny"])
    warning = amount(payload["warningPercent"])
    allocations = payload["allocations"]
    if not 1 <= warning <= 100 or not isinstance(allocations, list) or len(allocations) > 8:
        raise ProjectError("VALIDATION_FAILED", 422)
    limits = dict.fromkeys(STAGES, 0)
    seen = set()
    for allocation in allocations:
        if (
            set(allocation) != {"stage", "limitMicroCny"}
            or allocation["stage"] not in STAGES
            or allocation["stage"] in seen
        ):
            raise ProjectError("VALIDATION_FAILED", 422)
        seen.add(allocation["stage"])
        limits[allocation["stage"]] = amount(allocation["limitMicroCny"])
    if sum(limits.values()) > total:
        raise ProjectError("VALIDATION_FAILED", 422)
    if total < charged(db) or any(
        limit < charged(db, stage=stage) for stage, limit in limits.items()
    ):
        raise ProjectError("BUDGET_EXCEEDED")
    db.execute(
        "UPDATE projects SET budget_micro_cny=?,budget_warning_percent=? WHERE id=?",
        (total, warning, project["id"]),
    )
    for stage, limit in limits.items():
        db.execute("UPDATE stage_budgets SET limit_micro_cny=? WHERE stage=?", (limit, stage))


def check_limits(
    db: sqlite3.Connection,
    project: sqlite3.Row,
    stage: str,
    addition: int,
    task_id: str | None = None,
    authorization: int | None = None,
) -> None:
    limit = db.execute(
        "SELECT limit_micro_cny FROM stage_budgets WHERE stage=?", (stage,)
    ).fetchone()[0]
    if (
        charged(db) + addition > project["budget_micro_cny"]
        or charged(db, stage=stage) + addition > limit
    ):
        raise ProjectError("BUDGET_EXCEEDED")
    if (
        task_id is not None
        and authorization is not None
        and charged(db, task_id=task_id) + addition > authorization
    ):
        raise ProjectError("BUDGET_EXCEEDED")


def summary(db: sqlite3.Connection, project: sqlite3.Row) -> dict[str, Any]:
    settled, reserved = db.execute(
        "SELECT coalesce(sum(CASE WHEN state='settled' THEN settled_micro_cny ELSE 0 "
        "END),0),coalesce(sum(CASE WHEN state='pending' THEN reserved_micro_cny ELSE 0 "
        "END),0) FROM cost_entries"
    ).fetchone()
    remaining = db.execute(
        "SELECT coalesce(sum((s.maximum_calls-(SELECT count(*) FROM service_calls c WHERE "
        "c.step_id=s.id))*s.maximum_micro_cny),0) FROM planned_steps s JOIN task_plans p "
        "ON p.id=s.plan_id WHERE p.rowid=(SELECT max(newer.rowid) FROM task_plans newer "
        "WHERE newer.object_id=p.object_id AND "
        "json_extract(newer.plan_json,'$.phase')=json_extract(p.plan_json,'$.phase'))"
    ).fetchone()[0]
    for row in db.execute("SELECT state,amount_micro_cny FROM external_expenses"):
        if row["state"] == "settled":
            settled += row["amount_micro_cny"]
        elif row["state"] == "pending":
            reserved += row["amount_micro_cny"]
        else:
            remaining += row["amount_micro_cny"]
    return {
        "settledMicroCny": settled,
        "reservedMicroCny": reserved,
        "remainingWorkMicroCny": remaining,
        "reworkScenarioMicroCny": 0,
        "forecastMicroCny": settled + reserved + remaining,
        "budgetMicroCny": project["budget_micro_cny"],
        "containsUnknown": db.execute(
            "SELECT 1 FROM service_calls WHERE state IN "
            "('submitting','result_unknown','running') LIMIT 1"
        ).fetchone()
        is not None,
        "estimateVersion": "synthetic-price-v1"
        if project["execution_mode"] == "synthetic"
        else "unconfigured",
    }


def entries(db: sqlite3.Connection, cursor: str | None, limit: int) -> dict[str, Any]:
    from app.storage.tasks import cursor_rowid, page

    before = cursor_rowid(db, "cost_entries", "call_id", cursor, limit)
    rows = db.execute(
        "SELECT * FROM cost_entries WHERE rowid<? ORDER BY rowid DESC LIMIT ?", (before, limit + 1)
    )
    return page(
        [
            {
                "callId": r["call_id"],
                "state": r["state"],
                "reservedMicroCny": r["reserved_micro_cny"],
                "settledMicroCny": r["settled_micro_cny"],
                "basis": r["basis"],
            }
            for r in rows
        ],
        "callId",
        limit,
    )
