"""Deterministic local structure/reference reports, never semantic or quality evidence."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.storage import revisions
from app.storage.errors import ProjectError
from app.storage.settings import canonical
from app.storage.task_plans import identifier

Json = dict[str, Any]
RULES = ["structural", "references"]
VERSION = "local-structure-v1"


def report(db: sqlite3.Connection, check_id: str) -> Json:
    row = db.execute(
        "SELECT report_json FROM check_runs WHERE id=?", (identifier(check_id),)
    ).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    result: Json = json.loads(row[0])
    return result


def run(db: sqlite3.Connection, payload: Json, operation: str) -> str:
    revision_ids, rule_ids = payload["revisionIds"], payload["ruleIds"]
    if (
        not isinstance(revision_ids, list)
        or not 1 <= len(revision_ids) <= 1000
        or not isinstance(rule_ids, list)
        or not 1 <= len(rule_ids) <= 200
        or len(set(rule_ids)) != len(rule_ids)
        or not set(rule_ids) <= set(RULES)
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    if len(set(revision_ids)) != len(revision_ids):
        raise ProjectError("VALIDATION_FAILED", 422)
    targets = [revisions.get(db, rid) for rid in revision_ids]
    check_id, job_id = str(uuid4()), str(uuid4())
    issues: list[tuple[str, Json, str, str]] = []
    for target in targets:
        for rule in rule_ids:
            try:
                if rule == "structural":
                    revisions.validate_payload(target["payload"])
                else:
                    revisions.validate_references(db, target["payload"], target["id"])
                    if revisions.stale_inputs(db, target["id"]):
                        raise ProjectError("CHECK_REQUIRED")
            except ProjectError as error:
                issues.append((str(uuid4()), target, rule, error.code))
    result = {
        "id": check_id,
        "revisionIds": revision_ids,
        "ruleIds": rule_ids,
        "outcome": "fail" if issues else "pass",
        "issueIds": [item[0] for item in issues],
        "method": "local",
        "observedRanges": [],
        "evidenceMediaIds": [],
        "ruleVersion": VERSION,
        "limitations": (
            "Only deterministic payload structure and stored reference integrity were checked. "
            "No semantic, audiovisual quality, rights or human review was performed."
        ),
    }
    db.execute(
        "INSERT INTO check_runs VALUES(?,?,?,?)",
        (check_id, canonical(result), result["outcome"], datetime.now(UTC).isoformat()),
    )
    for issue_id, target, rule, code in issues:
        db.execute(
            "INSERT INTO checks VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                issue_id,
                target["artifactId"],
                target["id"],
                None,
                rule,
                VERSION,
                "local",
                "blocking",
                "open",
                canonical({"errorCode": code}),
                check_id,
            ),
        )
    db.execute(
        "INSERT INTO local_jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (job_id, "local_check", "succeeded", 0, 0, canonical(payload), check_id, None, operation),
    )
    return job_id


def require_coverage(
    db: sqlite3.Connection, revision_id: str, check_ids: list[str] | None = None
) -> None:
    if check_ids is None:
        reports = [
            json.loads(row[0])
            for row in db.execute(
                "SELECT report_json FROM check_runs WHERE outcome IN ('pass','not_applicable')"
            )
        ]
    else:
        if not isinstance(check_ids, list) or len(check_ids) > 1000:
            raise ProjectError("VALIDATION_FAILED", 422)
        reports = [report(db, rid) for rid in check_ids]
    covered: set[str] = set()
    for result in reports:
        if (
            result["method"] == "local"
            and result["ruleVersion"] == VERSION
            and result["outcome"] == "pass"
            and revision_id in result["revisionIds"]
        ):
            covered.update(result["ruleIds"])
    if not set(RULES) <= covered:
        raise ProjectError("CHECK_REQUIRED")
    if revisions.stale_inputs(db, revision_id):
        raise ProjectError("CHECK_REQUIRED")
    # Existing reports do not override a reference that went missing after the check.
    revisions.validate_references(db, revisions.get(db, revision_id)["payload"], revision_id)
