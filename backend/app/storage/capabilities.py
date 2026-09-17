"""Validated versioned profiles. No production network adapter is approved or registered."""

import copy
import json
import threading
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.settings import canonical

Json = dict[str, Any]
FreeChecker = Callable[[Json, Json], bool]
CHECK_TIMEOUT_SECONDS = 5.0


@cache
def validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((Path(__file__).parent / "capability.schema.json").read_text("utf-8"))
    )


def validate(profile: Json) -> None:
    if not validator().is_valid(profile):
        raise ProjectError("CAPABILITY_INVALID", 422)
    if profile["enabled"] and (
        profile["accountState"] != "available" or profile["interfaceState"] != "verified"
    ):
        raise ProjectError("CAPABILITY_INVALID", 422)
    if any(phase.split("_")[0] != profile["stage"] for phase in profile["phases"]):
        raise ProjectError("CAPABILITY_INVALID", 422)
    if len(set(profile["phases"])) != len(profile["phases"]):
        raise ProjectError("CAPABILITY_INVALID", 422)


def initialize(path: Path, profiles: list[Json]) -> None:
    for profile in profiles:
        validate(profile)
    with connect(path) as db, db:
        # Interrupted checks are never submitted again automatically.
        db.execute(
            "UPDATE global_jobs SET state='failed',result_json=? "
            "WHERE state IN ('queued','running')",
            (canonical({"errorCode": "CONNECTION_CHECK_FAILED"}),),
        )
        # Connection evidence is process-local until persistent credential identity is proved.
        for row in db.execute("SELECT id,profile_json FROM capabilities").fetchall():
            profile = json.loads(row["profile_json"])
            validate(profile)
            profile["accountState"] = "unknown"
            profile["enabled"] = False
            db.execute(
                "UPDATE capabilities SET profile_json=? WHERE id=?", (canonical(profile), row["id"])
            )
        for profile in profiles:
            profile = copy.deepcopy(profile)
            db.execute(
                "INSERT INTO capabilities VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "version=excluded.version,profile_json=excluded.profile_json,"
                "checked_at=excluded.checked_at",
                (profile["id"], profile["version"], canonical(profile), profile["priceDate"]),
            )


def get(path: Path, identifier: str) -> Json:
    with connect(path, "ro") as db:
        row = db.execute(
            "SELECT profile_json FROM capabilities WHERE id=?", (identifier,)
        ).fetchone()
    if row is None:
        raise ProjectError("CAPABILITY_UNAVAILABLE", 422)
    result: Json = json.loads(row[0])
    validate(result)
    return result


def list_profiles(path: Path) -> list[Json]:
    with connect(path, "ro") as db:
        values = [
            json.loads(row[0])
            for row in db.execute("SELECT profile_json FROM capabilities ORDER BY id")
        ]
    for value in values:
        validate(value)
    return values


def run_free_check(checker: FreeChecker, profile: Json, secret: Json) -> bool | None:
    """Adapter timeout/errors are static failures; the checker cannot log SDK exceptions here."""
    finished = threading.Event()
    result: list[bool | None] = []

    def run() -> None:
        try:
            value = checker(copy.deepcopy(profile), dict(secret))
            result.append(value if type(value) is bool else None)
        except Exception:
            result.append(None)
        finally:
            finished.set()

    threading.Thread(target=run, daemon=True, name="free-account-check").start()
    if not finished.wait(CHECK_TIMEOUT_SECONDS):
        return None
    return result[0]
