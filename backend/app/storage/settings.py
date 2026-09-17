"""Application configuration transactions and process-lifetime secret storage."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.storage import credentials
from app.storage.database import connect
from app.storage.errors import ProjectError

Json = dict[str, Any]


def canonical(value: Json) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def text(value: Any, maximum: int = 100) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ProjectError("VALIDATION_FAILED", 422)
    return value


def identity(command: Json, fields: set[str], provider: str = "") -> tuple[str, str]:
    if (
        set(command) != {"clientOperationId", "expectedRevision", "payload"}
        or type(command["expectedRevision"]) is not int
        or not 0 <= command["expectedRevision"] < 9007199254740991
        or not isinstance(command["payload"], dict)
        or set(command["payload"]) != fields
    ):
        raise ProjectError("VALIDATION_FAILED", 422)
    operation = command["clientOperationId"]
    if not isinstance(operation, str) or str(UUID(operation, version=4)) != operation:
        raise ProjectError("VALIDATION_FAILED", 422)
    return operation, hashlib.sha256(
        canonical({"provider": provider, "command": command}).encode()
    ).hexdigest()


def replay(db: sqlite3.Connection, operation: str, digest: str, name: str) -> Json | None:
    row = db.execute("SELECT * FROM global_operations WHERE id=?", (operation,)).fetchone()
    if row is None:
        return None
    if row["request_hash"] != digest or row["operation_name"] != name:
        raise ProjectError("OPERATION_ID_REUSED")
    result: Json = json.loads(row["receipt_json"])
    return result


def cas(db: sqlite3.Connection, command: Json) -> int:
    revision = int(db.execute("SELECT revision FROM settings WHERE singleton=1").fetchone()[0])
    if revision != command["expectedRevision"]:
        raise ProjectError("REVISION_CONFLICT")
    return revision + 1


def record(
    db: sqlite3.Connection,
    command: Json,
    digest: str,
    name: str,
    resource: str,
    revision: int,
    *,
    state: str = "committed",
) -> Json:
    receipt = {
        "operationId": command["clientOperationId"],
        "resourceId": resource,
        "committedRevision": revision,
        "state": state,
    }
    db.execute("UPDATE settings SET revision=? WHERE singleton=1", (revision,))
    # Only the irreversible request hash is retained; no original secret field names.
    db.execute(
        "INSERT INTO global_operations VALUES(?,?,?,?,?,?,?,?)",
        (command["clientOperationId"], digest, name, state, resource, canonical(receipt), "", "{}"),
    )
    return receipt


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.secrets: dict[str, tuple[Json, Json]] = {}
        self.profiles: dict[str, Json] = {}

    def clear(self) -> None:
        self.secrets.clear()
        self.profiles.clear()

    def details(self) -> Json:
        with connect(self.path, "ro") as db:
            entries = [
                {
                    "id": r["id"],
                    "providerId": r["provider_id"],
                    "kind": r["kind"],
                    "persistence": "dpapi",
                    "maskedSuffix": r["masked_suffix"],
                }
                for r in db.execute("SELECT * FROM credentials ORDER BY provider_id")
            ]
            profiles = [
                {
                    "id": r["id"],
                    "providerId": r["provider_id"],
                    "region": r["region"],
                    "bucket": r["bucket"],
                    "credentialRef": r["credential_id"],
                    "retentionHours": r["retention_hours"],
                    "persistence": "dpapi",
                }
                for r in db.execute("SELECT * FROM storage_profiles ORDER BY provider_id")
            ]
            probe = db.execute("SELECT ffmpeg_probe_json FROM settings").fetchone()[0]
        entries.extend(dict(entry) for entry, _ in self.secrets.values())
        profiles.extend(dict(profile) for profile in self.profiles.values())
        summary = None
        if probe:
            info = json.loads(probe)
            summary = {
                "version": info["version"][:200],
                "h264": info["h264"],
                "aac": info["aac"],
                "subtitles": info["libass"],
            }
        return {"credentials": entries, "storageProfiles": profiles, "toolSummary": summary}

    @staticmethod
    def invalidate(db: sqlite3.Connection, provider: str) -> None:
        for row in db.execute("SELECT * FROM capabilities").fetchall():
            profile = json.loads(row["profile_json"])
            if profile["providerId"] == provider:
                profile["accountState"] = "unknown"
                profile["enabled"] = False
                db.execute(
                    "UPDATE capabilities SET profile_json=? WHERE id=?",
                    (canonical(profile), row["id"]),
                )

    def set_credential(self, provider: str, command: Json) -> Json:
        text(provider)
        operation, digest = identity(command, {"secret", "persistence"}, provider)
        payload = command["payload"]
        secret = payload["secret"]
        if not isinstance(secret, dict) or payload["persistence"] not in {"dpapi", "session_only"}:
            raise ProjectError("VALIDATION_FAILED", 422)
        if secret.get("kind") == "api_key" and set(secret) == {"kind", "apiKey"}:
            key = text(secret["apiKey"], 8192)
            suffix = key[-4:] if len(key) > 4 else "****"
        elif secret.get("kind") == "oss" and set(secret) == {
            "kind",
            "accessKeyId",
            "accessKeySecret",
            "securityToken",
        }:
            text(secret["accessKeyId"], 256)
            key = text(secret["accessKeySecret"], 8192)
            suffix = key[-4:] if len(key) > 4 else "****"
            if secret["securityToken"] is not None:
                text(secret["securityToken"], 16384)
        else:
            raise ProjectError("VALIDATION_FAILED", 422)
        with connect(self.path) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = replay(db, operation, digest, "setCredential")
            if old is not None:
                return old
            revision = cas(db, command)
            encrypted = (
                credentials.protect(canonical(secret).encode())
                if payload["persistence"] == "dpapi"
                else None
            )
            resource = str(uuid4())
            db.execute(
                "DELETE FROM storage_profiles WHERE credential_id IN "
                "(SELECT id FROM credentials WHERE provider_id=?)",
                (provider,),
            )
            db.execute("DELETE FROM credentials WHERE provider_id=?", (provider,))
            if encrypted is not None:
                db.execute(
                    "INSERT INTO credentials VALUES(?,?,?,?,?)",
                    (resource, provider, secret["kind"], encrypted, suffix),
                )
            self.invalidate(db, provider)
            receipt = record(db, command, digest, "setCredential", resource, revision)
        self.secrets.pop(provider, None)
        self.profiles = {k: p for k, p in self.profiles.items() if p["providerId"] != provider}
        if encrypted is None:
            self.secrets[provider] = (
                {
                    "id": resource,
                    "providerId": provider,
                    "kind": secret["kind"],
                    "persistence": "session_only",
                    "maskedSuffix": suffix,
                },
                dict(secret),
            )
        return receipt

    def delete_credential(self, provider: str, command: Json) -> Json:
        text(provider)
        operation, digest = identity(command, {"confirmed"}, provider)
        if command["payload"]["confirmed"] is not True:
            raise ProjectError("VALIDATION_FAILED", 422)
        with connect(self.path) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = replay(db, operation, digest, "deleteCredential")
            if old is not None:
                return old
            revision = cas(db, command)
            row = db.execute(
                "SELECT id FROM credentials WHERE provider_id=?", (provider,)
            ).fetchone()
            memory = self.secrets.get(provider)
            if row is None and memory is None:
                raise ProjectError("OBJECT_NOT_FOUND", 404)
            resource = row[0] if row else memory[0]["id"] if memory else ""
            db.execute("DELETE FROM storage_profiles WHERE credential_id=?", (resource,))
            db.execute("DELETE FROM credentials WHERE provider_id=?", (provider,))
            self.invalidate(db, provider)
            receipt = record(db, command, digest, "deleteCredential", resource, revision)
        self.secrets.pop(provider, None)
        self.profiles = {k: p for k, p in self.profiles.items() if p["credentialRef"] != resource}
        return receipt

    def configure_storage(self, command: Json) -> Json:
        operation, digest = identity(
            command, {"providerId", "region", "bucket", "credentialRef", "retentionHours"}
        )
        payload = command["payload"]
        for field in ("providerId", "region", "bucket", "credentialRef"):
            text(payload[field], 256)
        retention = payload["retentionHours"]
        if type(retention) is not int or not 1 <= retention <= 168:
            raise ProjectError("VALIDATION_FAILED", 422)
        with connect(self.path) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = replay(db, operation, digest, "configureStorage")
            if old is not None:
                return old
            revision = cas(db, command)
            row = db.execute(
                "SELECT * FROM credentials WHERE id=? AND provider_id=? AND kind='oss'",
                (payload["credentialRef"], payload["providerId"]),
            ).fetchone()
            memory = self.secrets.get(payload["providerId"])
            if row is None and (
                memory is None
                or memory[0]["id"] != payload["credentialRef"]
                or memory[0]["kind"] != "oss"
            ):
                raise ProjectError("CREDENTIAL_UNAVAILABLE", 422)
            resource = str(uuid4())
            db.execute("DELETE FROM storage_profiles WHERE provider_id=?", (payload["providerId"],))
            if row is not None:
                db.execute(
                    "INSERT INTO storage_profiles VALUES(?,?,?,?,?,?)",
                    (
                        resource,
                        payload["providerId"],
                        payload["bucket"],
                        payload["region"],
                        payload["credentialRef"],
                        retention,
                    ),
                )
            receipt = record(db, command, digest, "configureStorage", resource, revision)
        self.profiles.pop(payload["providerId"], None)
        if row is None:
            self.profiles[payload["providerId"]] = {
                "id": resource,
                **payload,
                "persistence": "session_only",
            }
        return receipt

    def secret(self, provider: str) -> Json:
        if provider in self.secrets:
            return dict(self.secrets[provider][1])
        with connect(self.path, "ro") as db:
            row = db.execute(
                "SELECT dpapi_ciphertext FROM credentials WHERE provider_id=?", (provider,)
            ).fetchone()
        if row is None:
            raise ProjectError("CREDENTIAL_UNAVAILABLE", 422)
        try:
            result: Json = json.loads(credentials.unprotect(row[0]))
            return result
        except Exception:
            raise ProjectError("CREDENTIAL_UNAVAILABLE", 422) from None
